#!/usr/bin/env python3
"""Unified deal, direct-store promotion, archive & cross-store price monitor."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import dataclasses
import datetime as dt
import html
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
PRICE_RE = re.compile(
    r"(?:~?\s*\d[\d\s.,]{0,12}\s?(?:zł|PLN|€|\$|USD|EUR)|\$\s?\d[\d.,]{0,10})",
    re.IGNORECASE,
)
DISCOUNT_PCT_RE = re.compile(
    r"(?:-\s*(\d{1,2})\s*%|\b(\d{1,2})\s*%\s*(?:taniej|rabatu|zniżki|off)|rabat(?:y|em)?\s*(?:do\s*)?-?(\d{1,2})\s*%)",
    re.IGNORECASE,
)
OLD_PRICE_RE = re.compile(
    r"(?:zamiast|cena\s*kat\.?|katalogowa|poprzednia|średnia\s*cena[^:]*:|najniższa\s*cena[^:]*:|normalnie|regularna|cena\s*przed\s*obniżką:?)\s*(?:ok\.?\s*)?(\d[\d\s.,]{0,12})\s*(?:zł|PLN)",
    re.IGNORECASE,
)
SAVINGS_PLN_RE = re.compile(
    r"(?:do\s+)?(\d[\d\s.,]{0,10})\s*(?:zł|PLN)\s*(?:taniej|oszczędności|rabatu)",
    re.IGNORECASE,
)
LIDL_GRID_RE = re.compile(r'data-grid-data="([^"]+)"')
CENEO_ROW_RE = re.compile(
    r'data-pid="(\d+)"[^>]*?data-productminprice="([^"]*)"[^>]*?data-productName="([^"]*)"',
    re.IGNORECASE | re.DOTALL,
)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Deal:
    """Normalized representation of a deal, direct store promotion, or leaflet."""

    source: str
    deal_id: str
    title: str
    link: str
    published: str
    summary: str
    image_url: str = ""
    price: str = ""
    old_price: str = ""
    lowest_30d: str = ""
    merchant: str = ""
    category: str = ""
    store_group: str = ""
    discount_pct: int = 0
    savings_pln: float = 0.0
    deal_score: float = 0.0
    is_leaflet: bool = False
    ceneo_url: str = ""
    price_status: str = ""
    price_verdict: str = ""
    compared_offers: list[dict[str, str]] = field(default_factory=list)
    price_history: list[dict[str, str]] = field(default_factory=list)


def clean_html(raw_text: str | None, max_len: int = 240) -> str:
    """Strip HTML tags, unescape entities, and normalize whitespace."""
    if not raw_text:
        return ""
    text = HTML_TAG_RE.sub(" ", raw_text)
    text = html.unescape(text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def parse_pln_number(raw: str) -> float | None:
    """Parse a Polish/European price string into a float PLN value."""
    if not raw:
        return None
    cleaned = raw.replace("\xa0", " ").strip()
    m = re.search(r"(\d[\d\s.,]*)", cleaned)
    if not m:
        return None
    num_str = m.group(1).replace(" ", "")
    if "," in num_str and "." in num_str:
        if num_str.rfind(",") > num_str.rfind("."):
            num_str = num_str.replace(".", "").replace(",", ".")
        else:
            num_str = num_str.replace(",", "")
    elif "," in num_str:
        num_str = num_str.replace(",", ".")
    elif "." in num_str:
        parts = num_str.split(".")
        if len(parts[-1]) == 3 and len(parts[0]) <= 3:
            num_str = "".join(parts)
    try:
        val = float(num_str)
        return val if val > 0 else None
    except ValueError:
        return None


def format_pln(value: float) -> str:
    """Format float PLN price nicely in Polish notation."""
    if value.is_integer():
        return f"{int(value)} zł"
    return f"{value:.2f} zł".replace(".", ",")


def compute_discount_metrics(
    title: str, summary: str, price: str, explicit_old_price: str = ""
) -> tuple[str, int, float, float]:
    """Extract old price, discount percentage, PLN savings, and ranking score."""
    haystack = f"{title} {summary}"
    low = haystack.lower()

    explicit_pcts: list[int] = []
    for m in DISCOUNT_PCT_RE.finditer(haystack):
        for group in m.groups():
            if group and group.isdigit():
                val = int(group)
                if 1 <= val <= 99:
                    explicit_pcts.append(val)
    discount_pct = max(explicit_pcts, default=0)

    if any(k in low for k in ("za darmo", "darmowe gry", "gratis", "100% taniej")):
        discount_pct = max(discount_pct, 100)

    old_price = explicit_old_price
    old_val = parse_pln_number(explicit_old_price) if explicit_old_price else None
    if old_val is None:
        old_match = OLD_PRICE_RE.search(haystack)
        if old_match:
            old_val = parse_pln_number(old_match.group(1))
            if old_val:
                old_price = format_pln(old_val)

    cur_val = (
        parse_pln_number(price)
        if ("zł" in price.lower() or "pln" in price.lower() or not price)
        else None
    )
    if cur_val is None:
        m_pln = re.search(r"(\d[\d\s.,]{0,10})\s*(?:zł|PLN)", haystack, re.IGNORECASE)
        if m_pln:
            cur_val = parse_pln_number(m_pln.group(1))

    savings_pln = 0.0
    if old_val and cur_val and old_val > cur_val:
        savings_pln = round(old_val - cur_val, 2)
        computed_pct = round(((old_val - cur_val) / old_val) * 100)
        if 1 <= computed_pct <= 99:
            discount_pct = max(discount_pct, int(computed_pct))

    sav_match = SAVINGS_PLN_RE.search(haystack)
    if sav_match:
        parsed_sav = parse_pln_number(sav_match.group(1))
        if parsed_sav:
            savings_pln = max(savings_pln, round(parsed_sav, 2))

    bonus = 0.0
    if "błąd cenowy" in low or "blad cenowy" in low:
        bonus += 35.0
    if "historycznie najniższa" in low:
        bonus += 20.0
    if "1+1" in low or "2+1" in low or ("drugi" in low and "taniej" in low):
        bonus += 15.0

    deal_score = round(discount_pct * 2.0 + min(savings_pln / 20.0, 40.0) + bonus, 2)
    return old_price, discount_pct, savings_pln, deal_score


def sort_deals_by_best(deals: list[Deal]) -> list[Deal]:
    """Sort deals from biggest discount/deal score at the top."""
    return sorted(
        deals,
        key=lambda d: (0 if d.is_leaflet else 1, d.deal_score, d.discount_pct, d.savings_pln),
        reverse=True,
    )


def _local_name(tag: str) -> str:
    """Return XML tag name without namespace prefix."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _child_text(element: ET.Element, *names: str) -> str:
    """Return text of the first matching child tag (ignoring XML namespaces)."""
    for child in element:
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _all_child_texts(element: ET.Element, *names: str) -> list[str]:
    """Return all matching child tag texts (ignoring XML namespaces)."""
    values: list[str] = []
    for child in element:
        if _local_name(child.tag) in names and child.text:
            val = child.text.strip()
            if val:
                values.append(val)
    return values


def _atom_link(element: ET.Element) -> str:
    """Extract href from an Atom <link> element."""
    for child in element:
        if _local_name(child.tag) == "link":
            rel = child.attrib.get("rel", "alternate")
            href = child.attrib.get("href", "").strip()
            if href and rel in ("alternate", ""):
                return href
    return _child_text(element, "link")


def _extract_image_url(entry: ET.Element, raw_html_parts: list[str]) -> str:
    """Extract product/deal image URL from media tags, enclosures, or embedded HTML."""
    for child in entry:
        tag = _local_name(child.tag)
        if tag in ("content", "thumbnail") and child.attrib.get("url"):
            medium = child.attrib.get("medium", "image")
            if medium == "image" or tag == "thumbnail":
                return child.attrib["url"].strip()
        if tag == "enclosure" and child.attrib.get("url"):
            mime = child.attrib.get("type", "")
            if not mime or mime.startswith("image/"):
                return child.attrib["url"].strip()

    for part in raw_html_parts:
        if not part:
            continue
        match = IMG_SRC_RE.search(html.unescape(part))
        if match:
            return match.group(1).strip()
    return ""


def _extract_merchant_and_price(
    entry: ET.Element, title: str, summary: str, categories: list[str]
) -> tuple[str, str]:
    """Extract merchant name and price from Pepper metadata or title/summary fallback."""
    merchant = ""
    price = ""
    for child in entry:
        if _local_name(child.tag) == "merchant":
            merchant = child.attrib.get("name", "").strip()
            price = child.attrib.get("price", "").strip()
            break

    if not price:
        match = PRICE_RE.search(title) or PRICE_RE.search(summary)
        if match:
            price = WHITESPACE_RE.sub(" ", match.group(0)).strip()

    if not merchant and categories:
        for cat in categories:
            if "." in cat:
                merchant = cat
                break

    return merchant, price


def parse_feed(
    xml_bytes: bytes, source_name: str, store_group: str = "", limit: int = 30
) -> list[Deal]:
    """Parse RSS 2.0 or Atom XML bytes into a list of Deal objects."""
    root = ET.fromstring(xml_bytes.lstrip())
    root_name = _local_name(root.tag)

    entries: list[ET.Element] = []
    if root_name == "rss":
        channel = next((c for c in root if _local_name(c.tag) == "channel"), None)
        if channel is not None:
            entries = [c for c in channel if _local_name(c.tag) == "item"]
    elif root_name == "feed":
        entries = [c for c in root if _local_name(c.tag) == "entry"]
    else:
        entries = [el for el in root.iter() if _local_name(el.tag) in ("item", "entry")]

    deals: list[Deal] = []
    for entry in entries[:limit]:
        title = clean_html(_child_text(entry, "title"), max_len=200)
        link = _atom_link(entry) if root_name == "feed" else _child_text(entry, "link")
        deal_id = _child_text(entry, "guid", "id") or link or f"{source_name}:{title}"
        published = _child_text(entry, "pubDate", "published", "updated", "date")

        raw_desc = _child_text(entry, "description", "summary")
        raw_encoded = _child_text(entry, "encoded", "content")
        summary = clean_html(raw_desc or raw_encoded)

        categories = _all_child_texts(entry, "category")
        image_url = _extract_image_url(entry, [raw_desc, raw_encoded])
        merchant, price = _extract_merchant_and_price(entry, title, summary, categories)
        category = categories[0] if categories else ""
        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, summary, price
        )

        if not title and not link:
            continue
        deals.append(
            Deal(
                source=source_name,
                deal_id=deal_id,
                title=title or "(brak tytułu)",
                link=link,
                published=published,
                summary=summary,
                image_url=image_url,
                price=price,
                old_price=old_price,
                merchant=merchant,
                category=category,
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
            )
        )
    return deals


def parse_lidl_page(
    html_bytes: bytes, source_name: str, store_group: str = "Spożywcze i markety", limit: int = 30
) -> list[Deal]:
    """Parse promotional product cards directly from Lidl.pl HTML data-grid-data JSON."""
    page = html_bytes.decode("utf-8", errors="ignore")
    deals: list[Deal] = []
    seen: set[str] = set()

    for m in LIDL_GRID_RE.finditer(page):
        try:
            obj = json.loads(html.unescape(m.group(1)))
        except json.JSONDecodeError:
            continue

        title = str(obj.get("fullTitle") or obj.get("title") or "").strip()
        if not title:
            continue
        pid = str(obj.get("productId") or obj.get("erpNumber") or title)
        if pid in seen:
            continue
        seen.add(pid)

        rel_url = str(obj.get("canonicalUrl") or obj.get("canonicalPath") or "").strip()
        link = f"https://www.lidl.pl{rel_url}" if rel_url.startswith("/") else rel_url
        image = str(obj.get("image") or "").strip()
        category = str(obj.get("category") or "Lidl Promocje").strip()

        price_info = obj.get("price") or {}
        cur_num = price_info.get("price")
        price_str = format_pln(float(cur_num)) if isinstance(cur_num, (int, float)) else ""
        disc = price_info.get("discount") or {}
        old_num = disc.get("deletedPrice")
        old_str = format_pln(float(old_num)) if isinstance(old_num, (int, float)) else ""
        pct = int(disc.get("percentageDiscount") or 0)
        abs_disc = float(disc.get("absoluteDiscount") or 0.0)
        if not abs_disc and isinstance(old_num, (int, float)) and isinstance(cur_num, (int, float)):
            abs_disc = max(0.0, round(float(old_num) - float(cur_num), 2))
        hint = str(disc.get("bargainHintText") or "").strip()

        score = round(pct * 2.0 + min(abs_disc / 20.0, 40.0), 2)
        summary = f"{hint + ' • ' if hint else ''}Promocja bezpośrednio ze sklepu Lidl.pl."

        deals.append(
            Deal(
                source=source_name,
                deal_id=f"lidl:{pid}",
                title=title,
                link=link,
                published="Aktualna oferta Lidl.pl",
                summary=summary,
                image_url=image,
                price=price_str,
                old_price=old_str,
                lowest_30d=old_str,
                merchant="Lidl.pl",
                category=category,
                store_group=store_group,
                discount_pct=pct,
                savings_pln=abs_disc,
                deal_score=score,
                is_leaflet=False,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def parse_dino_page(
    html_bytes: bytes, source_name: str, store_group: str = "Spożywcze i markety", limit: int = 30
) -> list[Deal]:
    """Parse promotional products directly from marketdino.pl HTML."""
    page = html_bytes.decode("utf-8", errors="ignore")
    parts = page.split("Cena przed obniżką:")
    if len(parts) < 2:
        return []

    deals: list[Deal] = []
    seen_titles: set[str] = set()
    for idx in range(len(parts) - 1):
        before = parts[idx][-1400:]
        after = parts[idx + 1][:1200]

        img_matches = re.findall(
            r'src="(https://api\.marketdino\.pl/media/[^"]+\.(?:webp|png|jpg|jpeg)[^"]*)"',
            before,
            re.IGNORECASE,
        )
        image_url = html.unescape(img_matches[-1]) if img_matches else ""

        alt_matches = re.findall(r'alt="([^"]{3,120})"', before)
        title = ""
        if alt_matches:
            title = re.sub(r"\s*widok\s*\d+$", "", alt_matches[-1], flags=re.IGNORECASE).strip()
        if not title:
            tokens = [t.strip() for t in clean_html(before[-350:], max_len=350).split() if len(t.strip()) > 1]
            title = " ".join(tokens[-4:])
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        old_m = re.search(r"(\d+[.,]\d{2})\s*zł", after)
        old_val = parse_pln_number(old_m.group(1)) if old_m else None
        old_price = format_pln(old_val) if old_val else ""

        pv_m = re.search(r"product-price-view[^>]*>(.*?)</div>\s*</div>", after, re.S)
        cur_price = ""
        pct = 0
        if pv_m:
            pv_txt = clean_html(pv_m.group(1), max_len=120)
            pct_m = re.search(r"-(\d{1,2})\s*%", pv_txt)
            if pct_m:
                pct = int(pct_m.group(1))
            num_m = re.search(r"(\d+)\s+(\d{2})", pv_txt)
            if num_m:
                cur_val = parse_pln_number(f"{num_m.group(1)},{num_m.group(2)}")
                if cur_val:
                    cur_price = format_pln(cur_val)

        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, f"-{pct}%" if pct else "", cur_price, explicit_old_price=old_price
        )
        discount_pct = max(discount_pct, pct)
        deal_score = max(deal_score, round(discount_pct * 2.0 + min(savings_pln / 20.0, 40.0), 2))

        deals.append(
            Deal(
                source=source_name,
                deal_id=f"dino:{title.lower()}",
                title=f"Dino: {title}",
                link="https://marketdino.pl/",
                published="Aktualna oferta Dino",
                summary="Promocja bezpośrednio ze strony marketdino.pl.",
                image_url=image_url,
                price=cur_price,
                old_price=old_price,
                lowest_30d=old_price,
                merchant="Dino",
                category="Spożywcze",
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
                is_leaflet=False,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def parse_biedronka_home_page(
    html_bytes: bytes, source_name: str, store_group: str = "Budowlane i dom", limit: int = 30
) -> list[Deal]:
    """Parse promotional product cards directly from home.biedronka.pl."""
    page = html_bytes.decode("utf-8", errors="ignore")
    chunks = page.split('data-itemid="')[1:]
    deals: list[Deal] = []
    seen: set[str] = set()

    for chunk in chunks:
        pid = chunk.split('"', 1)[0].strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)

        link_m = re.search(r'href="(https://home\.biedronka\.pl/[^"]+\.html)"', chunk)
        link = link_m.group(1) if link_m else "https://home.biedronka.pl/promocje/"

        img_m = re.search(
            r'(?:data-src|src)="(https://home\.biedronka\.pl/dw/image/[^"]+)"', chunk
        )
        image_url = html.unescape(img_m.group(1)) if img_m else ""

        name_m = re.search(
            r'class="[^"]*product-tile__name[^"]*"[^>]*>(.*?)</', chunk, re.S
        )
        title = clean_html(name_m.group(1), max_len=180) if name_m else ""
        if not title:
            alt_m = re.search(r'alt="([^"]{8,160})"', chunk)
            title = html.unescape(alt_m.group(1)).strip() if alt_m else ""
        if not title:
            continue

        raw_text = clean_html(chunk[:2600], max_len=900)
        prices = re.findall(r"(\d[\d.]*\s\d{2})\s*zł", raw_text)
        parsed_prices: list[float] = []
        for p in prices:
            val = parse_pln_number(p.replace(" ", ","))
            if val is not None:
                parsed_prices.append(val)

        cur_price = format_pln(parsed_prices[0]) if parsed_prices else ""
        old_price = (
            format_pln(parsed_prices[1])
            if len(parsed_prices) > 1 and parsed_prices[1] > parsed_prices[0]
            else ""
        )

        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, raw_text, cur_price, explicit_old_price=old_price
        )
        avail_note = (
            " (chwilowo niedostępny online)"
            if "produkt chwilowo niedostępny" in raw_text.lower()
            else ""
        )

        deals.append(
            Deal(
                source=source_name,
                deal_id=f"biedronka-home:{pid}",
                title=title,
                link=link,
                published="Biedronka Home",
                summary=f"Promocja ze sklepu Biedronka Home{avail_note}.",
                image_url=image_url,
                price=cur_price,
                old_price=old_price,
                lowest_30d=old_price,
                merchant="Biedronka Home",
                category="Dom i warsztat",
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
                is_leaflet=False,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def parse_biedronka_gazetki_page(
    html_bytes: bytes, source_name: str, store_group: str = "Spożywcze i markety", limit: int = 15
) -> list[Deal]:
    """Parse promotional leaflets directly from biedronka.pl/pl/gazetki (no Blix)."""
    page = html_bytes.decode("utf-8", errors="ignore")
    pattern = re.compile(
        r'href="(https://www\.biedronka\.pl/pl/press,id,([^,]+),title,([^"]+))"[^>]*>(.*?)</a>',
        re.S,
    )
    deals: list[Deal] = []
    seen: set[str] = set()
    for link, gid, slug, inner in pattern.findall(page):
        if gid in seen:
            continue
        seen.add(gid)
        img_m = re.search(r'src="(https://cdn\.biedronka\.pl/[^"]+)"', inner)
        image_url = img_m.group(1) if img_m else ""
        readable_title = slug.replace("-", " ").strip().capitalize()
        deals.append(
            Deal(
                source=source_name,
                deal_id=f"biedronka-gazetka:{gid}",
                title=f"Biedronka: {readable_title}",
                link=link,
                published="Oficjalna gazetka Biedronka.pl",
                summary="Bezpośrednia gazetka promocyjna ze strony biedronka.pl.",
                image_url=image_url,
                price="Gazetka",
                merchant="Biedronka.pl",
                category="Gazetki marketowe",
                store_group=store_group,
                deal_score=0.0,
                is_leaflet=True,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def parse_smyk_page(
    html_bytes: bytes, source_name: str, store_group: str = "Dzieci i zabawki", limit: int = 30
) -> list[Deal]:
    """Parse promotional products directly from smyk.com HTML."""
    page = html_bytes.decode("utf-8", errors="ignore")
    parts = page.split('class="horizontal-product__price--new"')
    if len(parts) < 2:
        return []

    deals: list[Deal] = []
    seen_links: set[str] = set()
    for idx in range(len(parts) - 1):
        before = parts[idx][-2400:]
        after = parts[idx + 1][:700]

        link_m = re.findall(r'href="(/pl/pl/p/[^"]+)"', before)
        if not link_m:
            continue
        rel_link = link_m[-1]
        if rel_link in seen_links:
            continue
        seen_links.add(rel_link)
        link = f"https://www.smyk.com{rel_link}"

        aria_m = re.findall(r'aria-label="([^"]{6,180})"', before)
        title = html.unescape(aria_m[-1]).strip() if aria_m else rel_link.split("/")[-1]

        img_m = re.findall(r'src="(https://img\.smyk\.com/[^"]+)"', before)
        image_url = html.unescape(img_m[-1]) if img_m else ""

        cur_txt = clean_html(after[:120], max_len=120)
        cur_m = re.search(r"(\d[\d\s]*[.,]\d{2})\s*zł", cur_txt)
        cur_val = parse_pln_number(cur_m.group(1)) if cur_m else None
        cur_price = format_pln(cur_val) if cur_val else ""

        old_m = re.search(r'horizontal-product__price--old"[^>]*>(.*?)</span>', after, re.S)
        old_val = parse_pln_number(clean_html(old_m.group(1))) if old_m else None
        old_price = format_pln(old_val) if old_val else ""

        omni_m = re.search(r'horizontal-product__omnibus--price"[^>]*>(.*?)</span>', after, re.S)
        omni_val = parse_pln_number(clean_html(omni_m.group(1))) if omni_m else None
        lowest_30d = format_pln(omni_val) if omni_val else old_price

        red_m = re.search(r"-(\d{1,2})\s*%", after)
        pct = int(red_m.group(1)) if red_m else 0

        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, f"-{pct}%", cur_price, explicit_old_price=old_price
        )
        discount_pct = max(discount_pct, pct)
        deal_score = max(deal_score, round(discount_pct * 2.0 + min(savings_pln / 20.0, 40.0), 2))

        deals.append(
            Deal(
                source=source_name,
                deal_id=f"smyk:{rel_link}",
                title=title,
                link=link,
                published="Aktualna oferta Smyk.com",
                summary=f"Promocja ze sklepu Smyk.com{f' • Najniższa z 30 dni: {lowest_30d}' if lowest_30d else ''}.",
                image_url=image_url,
                price=cur_price,
                old_price=old_price,
                lowest_30d=lowest_30d,
                merchant="Smyk.com",
                category="Dzieci i zabawki",
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
                is_leaflet=False,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def _find_rossmann_products(obj: Any) -> list[dict[str, Any]]:
    """Recursively locate product list in Rossmann Next.js __NEXT_DATA__ JSON."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if "price" in obj[0] and "navigateUrl" in obj[0] and "pictures" in obj[0]:
            return obj
    if isinstance(obj, dict):
        for val in obj.values():
            found = _find_rossmann_products(val)
            if found:
                return found
    elif isinstance(obj, list):
        for val in obj:
            found = _find_rossmann_products(val)
            if found:
                return found
    return []


def parse_rossmann_page(
    html_bytes: bytes, source_name: str, store_group: str = "Odzież i uroda", limit: int = 30
) -> list[Deal]:
    """Parse promotional products directly from Rossmann.pl __NEXT_DATA__ JSON."""
    page = html_bytes.decode("utf-8", errors="ignore")
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    products = _find_rossmann_products(data)
    deals: list[Deal] = []
    for p in products[:limit]:
        brand = str(p.get("brand") or "").strip()
        caption = str(p.get("caption") or p.get("fallbackCaption") or p.get("name") or "").strip()
        title = f"{brand} {caption}".strip()
        if not title:
            continue

        pid = str(p.get("id") or title)
        nav = str(p.get("navigateUrl") or "").strip()
        link = f"https://www.rossmann.pl{nav}" if nav.startswith("/") else nav

        pics = p.get("pictures") or []
        image_url = ""
        if pics and isinstance(pics[0], dict):
            image_url = str(pics[0].get("medium") or pics[0].get("small") or "").strip()

        cur_num = p.get("price")
        old_num = p.get("oldPrice")
        low_num = p.get("lastLowestPriceV2")
        cur_price = format_pln(float(cur_num)) if isinstance(cur_num, (int, float)) else ""
        old_price = format_pln(float(old_num)) if isinstance(old_num, (int, float)) else ""
        lowest_30d = format_pln(float(low_num)) if isinstance(low_num, (int, float)) else old_price

        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, "", cur_price, explicit_old_price=old_price
        )
        cat = str(p.get("category") or "Uroda").strip()
        deals.append(
            Deal(
                source=source_name,
                deal_id=f"rossmann:{pid}",
                title=title,
                link=link,
                published="Aktualna promocja Rossmann.pl",
                summary=f"Promocja w drogerii Rossmann.pl{f' • Najniższa z 30 dni: {lowest_30d}' if lowest_30d else ''}.",
                image_url=image_url,
                price=cur_price,
                old_price=old_price,
                lowest_30d=lowest_30d,
                merchant="Rossmann.pl",
                category=cat,
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
                is_leaflet=False,
            )
        )
    return deals


def parse_castorama_page(
    html_bytes: bytes, source_name: str, store_group: str = "Budowlane i dom", limit: int = 30
) -> list[Deal]:
    """Parse promotional product cards directly from Castorama.pl HTML."""
    page = html_bytes.decode("utf-8", errors="ignore")
    chunks = page.split('data-testid="product-link"')[1:]
    deals: list[Deal] = []
    seen: set[str] = set()

    for chunk in chunks:
        blk = chunk[:4500]
        href_m = re.search(r'href="(/[^"]+\.prd)"', blk)
        if not href_m:
            continue
        rel_url = href_m.group(1)
        if rel_url in seen:
            continue
        seen.add(rel_url)
        link = f"https://www.castorama.pl{rel_url}"

        slug_title = rel_url.strip("/").split("/")[0].replace("-", " ").capitalize()
        title_m = re.search(r'data-testid="product-title"[^>]*>(.*?)</', blk, re.S)
        title = clean_html(title_m.group(1), max_len=180) if title_m else slug_title

        img_m = re.search(r'(?:srcSet|src)="(https://media2\.castorama\.pl/[^"\s]+)"', blk)
        image_url = html.unescape(img_m.group(1)) if img_m else ""

        old_m = re.search(r"Oryginalna cena\s*(?:<!--\s*-->\s*)?(\d[\d\s.,]*)\s*zł", blk)
        old_val = parse_pln_number(old_m.group(1)) if old_m else None
        old_price = format_pln(old_val) if old_val else ""

        txt = clean_html(blk, max_len=1200)
        prices = re.findall(r"(\d[\d\s]*[.,]\d{2}|\d[\d\s]+)\s*zł", txt)
        cur_price = ""
        for p in reversed(prices):
            val = parse_pln_number(p)
            if val and (not old_val or val != old_val):
                cur_price = format_pln(val)
                break
        if not cur_price and prices:
            val = parse_pln_number(prices[-1])
            cur_price = format_pln(val) if val else ""

        old_price, discount_pct, savings_pln, deal_score = compute_discount_metrics(
            title, txt, cur_price, explicit_old_price=old_price
        )
        deals.append(
            Deal(
                source=source_name,
                deal_id=f"castorama:{rel_url}",
                title=title,
                link=link,
                published="Aktualna oferta Castorama.pl",
                summary=f"Oferta z marketu budowlanego Castorama.pl{f' • Najniższa z 30 dni: {old_price}' if old_price else ''}.",
                image_url=image_url,
                price=cur_price,
                old_price=old_price,
                lowest_30d=old_price,
                merchant="Castorama.pl",
                category="Budowlane i ogród",
                store_group=store_group,
                discount_pct=discount_pct,
                savings_pln=savings_pln,
                deal_score=deal_score,
                is_leaflet=False,
            )
        )
        if len(deals) >= limit:
            break
    return deals


def _build_ssl_context() -> ssl.SSLContext:
    """Create an SSL context using macOS system CA bundle when available."""
    ca_bundle = Path("/etc/ssl/cert.pem")
    if ca_bundle.exists():
        return ssl.create_default_context(cafile=str(ca_bundle))
    return ssl.create_default_context()


def fetch_feed(url: str, timeout: int = 15) -> bytes:
    """Download RSS/Atom/HTML bytes with a browser-like User-Agent."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.8",
        },
    )
    context = _build_ssl_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def build_search_query(title: str) -> str:
    """Extract clean product/model keywords from a deal title for Ceneo/Pepper search."""
    cleaned = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title)
    cleaned = re.sub(
        r"\b(?:za|od|tylko|jedyne|cena|kat\.?|zamiast|promocja|wyprzedaż|black\s*friday|weekend|rabat\w*|taniej|w\s+sklepie|na\s+allegro|w\s+amazon\w*|amazon\w*|x-kom|empik|media\s*expert|ceneo|steam|xbox|ps5|ps4|switch|wszystkie|kolory|w\s+tej\s+samej|cenie|dino|lidl|biedronka|smyk|rossmann|castorama)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\d[\d\s.,]*\s*(?:zł|pln|€|\$)", " ", cleaned, flags=re.IGNORECASE)
    tokens = [t for t in re.findall(r"[A-Za-z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ+-]+", cleaned) if len(t) >= 2]
    return " ".join(tokens[:5])


def build_ceneo_search_url(title: str) -> str:
    """Build a clean Ceneo search URL using '+'-separated product keywords."""
    query = build_search_query(title) or title[:50]
    return f"https://www.ceneo.pl/;szukaj-{urllib.parse.quote_plus(query)}"


def _parse_ceneo_offers(product_html: str, limit: int = 5) -> list[dict[str, str]]:
    """Extract individual store offers (shop name + price) from a Ceneo product page."""
    offers: list[dict[str, str]] = []
    seen_shops: set[str] = set()
    parts = re.split(r'data-shop="\d+"', product_html)[1:]
    for part in parts:
        chunk = part[:2200]
        alt_m = re.search(r'alt="([^"]+)"', chunk)
        val_m = re.search(r'class="value"[^>]*>([^<]+)<', chunk)
        pen_m = re.search(r'class="penny"[^>]*>([^<]+)<', chunk)
        if not alt_m or not val_m:
            continue
        shop = html.unescape(alt_m.group(1)).strip()
        if shop in seen_shops or shop in ("Zaufane opinie", "Program Ochrony Kupujących"):
            continue
        seen_shops.add(shop)
        price_str = f"{val_m.group(1).strip()}{pen_m.group(1).strip() if pen_m else ''} zł"
        offers.append({"shop": shop, "price": price_str})
        if len(offers) >= limit:
            break
    return offers


def compare_product_on_ceneo(
    title: str, deal_price_str: str, timeout: int = 8
) -> dict[str, Any]:
    """Search Ceneo for the product and compare its market prices against the deal."""
    query = build_search_query(title)
    if not query:
        return {"matched": False, "query": "", "verdict": "", "status": "", "offers": []}

    search_url = f"https://www.ceneo.pl/;szukaj-{urllib.parse.quote_plus(query)}"
    try:
        search_html = fetch_feed(search_url, timeout=timeout).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"matched": False, "query": query, "search_url": search_url, "verdict": "", "status": "", "offers": []}

    rows = CENEO_ROW_RE.findall(search_html)
    if not rows:
        return {
            "matched": False,
            "query": query,
            "search_url": search_url,
            "verdict": "",
            "status": "",
            "offers": [],
        }

    q_tokens = {t.lower() for t in query.split() if len(t) >= 2}
    best_row = None
    best_overlap = -1
    for pid, min_p_raw, prod_name in rows[:8]:
        pname = html.unescape(prod_name).strip()
        p_tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9ąćęłńóśźż]+", pname)}
        overlap = len(q_tokens & p_tokens)
        if overlap > best_overlap:
            best_overlap = overlap
            best_row = (pid, min_p_raw, pname)

    if not best_row or best_overlap < min(2, len(q_tokens)):
        return {
            "matched": False,
            "query": query,
            "search_url": search_url,
            "verdict": "",
            "status": "",
            "offers": [],
        }

    pid, min_p_raw, prod_name = best_row
    ceneo_min = parse_pln_number(min_p_raw)
    ceneo_url = f"https://www.ceneo.pl/{pid}"

    offers: list[dict[str, str]] = []
    try:
        prod_html = fetch_feed(ceneo_url, timeout=timeout).decode("utf-8", errors="ignore")
        offers = _parse_ceneo_offers(prod_html, limit=5)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    deal_val = parse_pln_number(deal_price_str) if ("zł" in deal_price_str.lower() or "pln" in deal_price_str.lower()) else None
    status = "market"
    verdict = f"Ceneo ({prod_name[:40]}): od {format_pln(ceneo_min)}" if ceneo_min else f"Ceneo: {prod_name[:40]}"

    if deal_val and ceneo_min:
        diff = round(ceneo_min - deal_val, 2)
        if diff > 1.0:
            pct = round((diff / ceneo_min) * 100)
            status = "cheapest"
            verdict = f"NAJTANIEJ! O {format_pln(diff)} (-{pct}%) taniej niż Ceneo (od {format_pln(ceneo_min)})"
        elif diff < -1.0:
            status = "cheaper_elsewhere"
            verdict = f"Taniej w innym sklepie! Ceneo od {format_pln(ceneo_min)} (taniej o {format_pln(-diff)})"
        else:
            status = "cheapest"
            verdict = f"Najniższa cena rynkowa (Ceneo od {format_pln(ceneo_min)})"

    return {
        "matched": True,
        "query": query,
        "product_name": prod_name,
        "ceneo_url": ceneo_url,
        "search_url": search_url,
        "ceneo_min": format_pln(ceneo_min) if ceneo_min else "",
        "status": status,
        "verdict": verdict,
        "offers": offers,
    }


def enrich_deals_with_ceneo(
    deals: list[Deal], history_path: Path, timestamp: str, max_compare: int = 8
) -> list[Deal]:
    """Compare top PLN non-leaflet deals against Ceneo and record store prices in history."""
    if max_compare <= 0:
        return deals

    candidates: list[int] = []
    for idx, deal in enumerate(deals):
        if deal.is_leaflet:
            continue
        if deal.price and ("zł" in deal.price.lower() or "pln" in deal.price.lower()):
            candidates.append(idx)
        if len(candidates) >= max_compare:
            break

    if not candidates:
        return deals

    results: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {
            pool.submit(compare_product_on_ceneo, deals[idx].title, deals[idx].price): idx
            for idx in candidates
        }
        for fut in concurrent.futures.as_completed(future_map):
            idx = future_map[fut]
            try:
                res = fut.result()
                if res.get("matched"):
                    results[idx] = res
            except Exception:
                pass

    if not results:
        return deals

    history_map = load_price_history(history_path)
    updated_deals = list(deals)
    for idx, res in results.items():
        deal = updated_deals[idx]
        key = product_key(deal)
        entries = list(history_map.get(key, []))

        existing_notes = {(e.get("date"), e.get("note"), e.get("price")) for e in entries}
        for off in res.get("offers", []):
            tup = (timestamp, f"Ceneo: {off['shop']}", off["price"])
            if tup not in existing_notes:
                entries.append({"date": timestamp, "price": off["price"], "note": f"Ceneo: {off['shop']}"})
                existing_notes.add(tup)
        if not res.get("offers") and res.get("ceneo_min"):
            tup = (timestamp, "Ceneo (najniższa)", res["ceneo_min"])
            if tup not in existing_notes:
                entries.append({"date": timestamp, "price": res["ceneo_min"], "note": "Ceneo (najniższa)"})

        entries = entries[-20:]
        history_map[key] = entries
        updated_deals[idx] = dataclasses.replace(
            deal,
            ceneo_url=res.get("ceneo_url", deal.ceneo_url),
            price_status=res.get("status", ""),
            price_verdict=res.get("verdict", ""),
            compared_offers=res.get("offers", []),
            price_history=entries,
        )

    history_path.write_text(json.dumps(history_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated_deals


def matches_filters(
    deal: Deal, keywords: list[str], exclude_keywords: list[str]
) -> bool:
    """Check whether a deal matches inclusion and exclusion keyword lists."""
    haystack = f"{deal.title} {deal.summary} {deal.merchant} {deal.category} {deal.store_group}".lower()
    if exclude_keywords and any(ex.lower() in haystack for ex in exclude_keywords):
        return False
    if not keywords:
        return True
    return any(kw.lower() in haystack for kw in keywords)


def product_key(deal: Deal) -> str:
    """Create a normalized key to track price observations for similar items over time."""
    if deal.is_leaflet:
        return deal.deal_id
    base = re.sub(r"\b(?:za|od)\s+\d[\d\s.,]*(?:zł|pln|€|\$).*$", "", deal.title.lower())
    words = re.findall(r"[a-z0-9ąćęłńóśźż]+", base)
    return " ".join(words[:6]) or deal.deal_id


def load_price_history(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load per-product price history dictionary."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def update_and_attach_price_history(
    path: Path, deals: list[Deal], timestamp: str
) -> list[Deal]:
    """Update price archive with current/Omnibus observations and attach Ceneo fallback links."""
    history_map = load_price_history(path)
    enriched: list[Deal] = []

    for deal in deals:
        key = product_key(deal)
        entries = list(history_map.get(key, []))
        if deal.lowest_30d and not any(e.get("note") == "Najniższa z 30 dni (Omnibus)" for e in entries):
            entries.insert(0, {"date": "30 dni przed obniżką", "price": deal.lowest_30d, "note": "Najniższa z 30 dni (Omnibus)"})
        elif deal.old_price and not any(e.get("note") == "przed promocją" for e in entries):
            entries.insert(0, {"date": "przed promocją", "price": deal.old_price, "note": "przed promocją"})
        if deal.price and not deal.is_leaflet:
            last_price = entries[-1].get("price") if entries else None
            if last_price != deal.price:
                entries.append({"date": timestamp, "price": deal.price, "note": deal.merchant or deal.source})
        entries = entries[-20:]
        if entries:
            history_map[key] = entries
        ceneo_link = deal.ceneo_url or ("" if deal.is_leaflet else build_ceneo_search_url(deal.title))
        enriched.append(dataclasses.replace(deal, price_history=entries, ceneo_url=ceneo_link))

    if len(history_map) > 2500:
        keys = list(history_map.keys())[-2500:]
        history_map = {k: history_map[k] for k in keys}
    path.write_text(json.dumps(history_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return enriched


def load_seen_ids(path: Path) -> set[str]:
    """Load previously seen deal IDs from JSON file."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(item) for item in data}
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def save_seen_ids(path: Path, seen_ids: set[str], max_keep: int = 5000) -> None:
    """Persist seen deal IDs to JSON file, keeping the set bounded."""
    trimmed = sorted(seen_ids)[-max_keep:]
    path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def save_latest_cache(
    path: Path, deals: list[Deal], errors: list[str], timestamp: str
) -> None:
    """Persist latest fetched deals with rich metadata for the web UI."""
    payload = {
        "updated_at": timestamp,
        "deals": [dataclasses.asdict(d) for d in deals],
        "errors": errors,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def send_notifications(new_deals: list[Deal], config: dict[str, Any]) -> None:
    """Send optional macOS native notification and/or free ntfy.sh push notification."""
    if not new_deals:
        return
    top = sort_deals_by_best(new_deals)[0]
    headline = f"Nowe okazje ({len(new_deals)})"
    body_parts = [top.title]
    if top.price:
        body_parts.append(top.price)
    if top.discount_pct:
        body_parts.append(f"-{top.discount_pct}%")
    message = " • ".join(body_parts)

    if config.get("macos_notifications", False):
        safe_title = headline.replace('"', "'")
        safe_msg = message[:180].replace('"', "'")
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe_msg}" with title "{safe_title}"'],
                check=False,
                capture_output=True,
                timeout=3,
            )
        except OSError:
            pass

    topic = str(config.get("ntfy_topic", "")).strip()
    if topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{urllib.parse.quote(topic)}",
                data=message.encode("utf-8"),
                headers={"Title": headline.encode("utf-8")},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5, context=_build_ssl_context())
        except (urllib.error.URLError, OSError):
            pass


def append_csv(path: Path, deals: list[Deal], timestamp: str) -> None:
    """Append newly discovered deals to a CSV history file."""
    if not deals:
        return
    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not file_exists:
            writer.writerow(
                [
                    "checked_at",
                    "source",
                    "store_group",
                    "title",
                    "price",
                    "old_price",
                    "discount_pct",
                    "merchant",
                    "category",
                    "link",
                    "published",
                    "summary",
                ]
            )
        for deal in deals:
            writer.writerow(
                [
                    timestamp,
                    deal.source,
                    deal.store_group,
                    deal.title,
                    deal.price,
                    deal.old_price,
                    deal.discount_pct,
                    deal.merchant,
                    deal.category,
                    deal.link,
                    deal.published,
                    deal.summary,
                ]
            )


def render_markdown_report(
    deals: list[Deal],
    errors: list[str],
    keywords: list[str],
    timestamp: str,
    only_new: bool,
) -> str:
    """Format deals sorted from biggest discount/opportunity as a Markdown report."""
    sorted_deals = sort_deals_by_best(deals)
    lines: list[str] = [
        f"# Raport okazji — od największych ({timestamp})",
        "",
        f"- Tryb: **{'tylko nowe' if only_new else 'wszystkie dopasowane'}**",
        f"- Filtry słów kluczowych: `{', '.join(keywords) if keywords else 'brak (wszystkie okazje)'}`",
        f"- Liczba znalezionych okazji: **{len(sorted_deals)}**",
        "",
    ]

    if errors:
        lines.append("## Błędy pobierania")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    if not sorted_deals:
        lines.append("Brak nowych okazji spełniających kryteria.")
        return "\n".join(lines) + "\n"

    lines.append("## Największe okazje (posortowane od najwyższego rabatu)")
    lines.append("")
    for deal in sorted_deals:
        title_md = f"[{deal.title}]({deal.link})" if deal.link else deal.title
        disc_tag = f" **[-{deal.discount_pct}%]**" if deal.discount_pct else ""
        old_tag = f" (wcześniej {deal.old_price})" if deal.old_price else ""
        verdict_tag = f" | {deal.price_verdict}" if deal.price_verdict else ""
        meta_parts = [
            p
            for p in (
                deal.source,
                deal.price + old_tag if deal.price else "",
                deal.merchant,
                deal.published,
            )
            if p
        ]
        meta = f" — _{' | '.join(meta_parts)}{verdict_tag}_" if meta_parts else ""
        lines.append(f"- **{title_md}**{disc_tag}{meta}")
        if deal.summary:
            lines.append(f"  {deal.summary}")
    lines.append("")
    return "\n".join(lines)


def load_config(config_path: Path) -> dict[str, Any]:
    """Load JSON configuration file."""
    return json.loads(config_path.read_text(encoding="utf-8"))


def fetch_all_sources(config: dict[str, Any]) -> tuple[list[Deal], list[str]]:
    """Fetch and parse deals from all enabled RSS/Atom and direct store sources."""
    keywords = [str(k).strip() for k in config.get("keywords", []) if str(k).strip()]
    exclude_keywords = [
        str(k).strip() for k in config.get("exclude_keywords", []) if str(k).strip()
    ]
    max_items = int(config.get("max_items_per_source", 30))

    all_matched: list[Deal] = []
    errors: list[str] = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        name = str(source["name"])
        url = str(source["url"])
        source_type = str(source.get("type", "rss")).lower()
        store_group = str(source.get("store_group", "")).strip()
        try:
            raw_bytes = fetch_feed(url)
            if source_type == "lidl":
                deals = parse_lidl_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "dino":
                deals = parse_dino_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "biedronka_home":
                deals = parse_biedronka_home_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "biedronka_gazetki":
                deals = parse_biedronka_gazetki_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "smyk":
                deals = parse_smyk_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "rossmann":
                deals = parse_rossmann_page(raw_bytes, name, store_group=store_group, limit=max_items)
            elif source_type == "castorama":
                deals = parse_castorama_page(raw_bytes, name, store_group=store_group, limit=max_items)
            else:
                deals = parse_feed(raw_bytes, name, store_group=store_group, limit=max_items)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as exc:
            errors.append(f"{name} ({url}): {exc}")
            continue

        for deal in deals:
            if matches_filters(deal, keywords, exclude_keywords):
                all_matched.append(deal)

    return sort_deals_by_best(all_matched), errors


def run_monitor(config_path: Path, show_all: bool = False, dry_run: bool = False) -> int:
    """Execute one full monitoring cycle and write report/history/cache files."""
    base_dir = config_path.parent
    config = load_config(config_path)
    keywords = [str(k).strip() for k in config.get("keywords", []) if str(k).strip()]

    seen_path = base_dir / config.get("seen_file", "seen_deals.json")
    report_path = base_dir / config.get("report_file", "raport_okazji.md")
    csv_path = base_dir / config.get("csv_file", "historia_okazji.csv")
    cache_path = base_dir / config.get("cache_file", "latest_deals.json")
    history_path = base_dir / config.get("price_history_file", "price_history.json")

    seen_ids = load_seen_ids(seen_path)
    all_matched, errors = fetch_all_sources(config)
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    if not dry_run:
        all_matched = update_and_attach_price_history(history_path, all_matched, timestamp)
        auto_compare_n = int(config.get("auto_compare_top_n", 0))
        if auto_compare_n > 0:
            all_matched = enrich_deals_with_ceneo(
                all_matched, history_path, timestamp, max_compare=auto_compare_n
            )

    matched_deals: list[Deal] = []
    new_deals: list[Deal] = []
    for deal in all_matched:
        is_new = deal.deal_id not in seen_ids
        if is_new:
            new_deals.append(deal)
            seen_ids.add(deal.deal_id)
        if show_all or is_new:
            matched_deals.append(deal)

    report = render_markdown_report(
        matched_deals, errors, keywords, timestamp, only_new=not show_all
    )

    if not dry_run:
        report_path.write_text(report, encoding="utf-8")
        append_csv(csv_path, new_deals, timestamp)
        save_seen_ids(seen_path, seen_ids)
        save_latest_cache(cache_path, all_matched, errors, timestamp)
        send_notifications(new_deals, config)

    print(report)
    return 1 if errors and not matched_deals else 0


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Monitor okazji cenowych i sklepów.")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Ścieżka do pliku konfiguracyjnego JSON (domyślnie: config.json)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Pokaż wszystkie pasujące okazje, nie tylko nowe od ostatniego uruchomienia.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nie zapisuj raportu, CSV ani historii.",
    )
    args = parser.parse_args()
    return run_monitor(Path(args.config).resolve(), show_all=args.all, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
