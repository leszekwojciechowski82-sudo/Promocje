"""Offline unit tests for monitor_okazji.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor_okazji

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:pepper="http://www.pepper.com/rss" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Pepper.pl</title>
    <item>
      <category>Elektronika</category>
      <pepper:merchant name="Amazon.pl" price="399,00zł" />
      <media:content medium="image" url="https://static.pepper.pl/img/ssd.jpg" />
      <title>Dysk SSD NVMe 2TB za 399 PLN</title>
      <link>https://www.pepper.pl/promocje/ssd-2tb</link>
      <guid>pepper-1</guid>
      <pubDate>Sun, 22 Nov 2026 19:00:00 +0100</pubDate>
      <description>&lt;p&gt;Super &lt;b&gt;promocja&lt;/b&gt; -20% na dysk SSD.&lt;/p&gt;</description>
    </item>
    <item>
      <category>Zabawki</category>
      <title>Zestaw LEGO Star Wars</title>
      <link>https://www.pepper.pl/promocje/lego-sw</link>
      <guid>pepper-2</guid>
      <pubDate>Sun, 22 Nov 2026 18:30:00 +0100</pubDate>
      <description>&lt;img src="https://example.test/lego.jpg"/&gt; Cena 199 PLN zamiast 398 PLN.</description>
    </item>
  </channel>
</rss>
""".encode("utf-8")

SAMPLE_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom</title>
  <entry>
    <title>Laptop 16GB RAM - okazja</title>
    <link rel="alternate" href="https://example.com/laptop"/>
    <id>atom-1</id>
    <updated>2026-11-22T18:00:00Z</updated>
    <summary>Przecena o 500 PLN.</summary>
  </entry>
</feed>
"""

SAMPLE_LIDL = """
<div data-grid-data="{&quot;productId&quot;: 100410059, &quot;fullTitle&quot;: &quot;ESMARA Koszula nocna&quot;, &quot;canonicalUrl&quot;: &quot;/p/esmara/p100410059&quot;, &quot;image&quot;: &quot;https://www.lidl.pl/assets/img.jpg&quot;, &quot;category&quot;: &quot;Moda&quot;, &quot;price&quot;: {&quot;price&quot;: 18.5, &quot;discount&quot;: {&quot;deletedPrice&quot;: 36.99, &quot;percentageDiscount&quot;: 49, &quot;absoluteDiscount&quot;: 18.49}}}"></div>
""".encode("utf-8")

SAMPLE_DINO = """
<div>
  <img src="https://api.marketdino.pl/media/pieczarka.webp" alt="Pieczarka kg widok 1" />
  <p>Pieczarka</p>
  <span>Cena przed obniżką: <span>14,99 zł</span></span>
  <div class="product-price-view"><p>-46%</p><p>7</p><p>99</p></div></div>
</div>
""".encode("utf-8")

SAMPLE_SMYK = """
<div>
  <a aria-label="Hot Wheels City Mega Garaż" href="/pl/pl/p/hot-wheels-i8032404">
    <img src="https://img.smyk.com/hw.jpg" />
  </a>
  <span class="horizontal-product__price--new">159,99 zł</span>
  <span class="horizontal-product__price--old">289,00 zł</span>
  <span class="horizontal-product__price--reduction">-45%</span>
  <span class="horizontal-product__omnibus--price">289,00 zł</span>
</div>
""".encode("utf-8")

SAMPLE_ROSSMANN = """
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"products":[{"id":2140366,"brand":"Isana","caption":"kalendarz adwentowy","navigateUrl":"/Produkt/kalendarz,2140366","price":64.99,"oldPrice":99.99,"lastLowestPriceV2":79.99,"category":"Uroda","pictures":[{"medium":"https://pro-fra-s3-productsassets.rossmann.pl/img.webp"}]}]}}}
</script>
""".encode("utf-8")

SAMPLE_CASTORAMA = """
<a data-testid="product-link" href="/robot-koszacy-mac-allister/5063022_CAPL.prd">
  <img src="https://media2.castorama.pl/is/image/robot.jpg" />
  <span>Oryginalna cena 108 zł</span>
  <span>86,98 zł</span>
</a>
""".encode("utf-8")

SAMPLE_BIEDRONKA_GAZETKI = """
<a href="https://www.biedronka.pl/pl/press,id,j39u8xm17,title,biek-od-20-11">
  <img src="https://cdn.biedronka.pl/__2026/T48A/BIEK/310x475.png" />
</a>
""".encode("utf-8")


class MonitorOkazjiTests(unittest.TestCase):
    def test_parse_rss_metadata_and_sorting(self) -> None:
        deals = monitor_okazji.parse_feed(SAMPLE_RSS, "Pepper.pl")
        self.assertEqual(len(deals), 2)
        self.assertEqual(deals[0].discount_pct, 20)
        self.assertEqual(deals[1].discount_pct, 50)
        self.assertEqual(deals[1].old_price, "398 zł")
        self.assertAlmostEqual(deals[1].savings_pln, 199.0)

        sorted_deals = monitor_okazji.sort_deals_by_best(deals)
        self.assertEqual(sorted_deals[0].deal_id, "pepper-2")

    def test_parse_direct_stores(self) -> None:
        lidl = monitor_okazji.parse_lidl_page(SAMPLE_LIDL, "Lidl.pl (Promocje)")
        self.assertEqual(len(lidl), 1)
        self.assertEqual(lidl[0].discount_pct, 49)

        dino = monitor_okazji.parse_dino_page(SAMPLE_DINO, "Dino (Promocje)")
        self.assertEqual(len(dino), 1)
        self.assertEqual(dino[0].price, "7,99 zł")
        self.assertEqual(dino[0].old_price, "14,99 zł")
        self.assertGreaterEqual(dino[0].discount_pct, 46)

        smyk = monitor_okazji.parse_smyk_page(SAMPLE_SMYK, "Smyk.com")
        self.assertEqual(len(smyk), 1)
        self.assertEqual(smyk[0].price, "159,99 zł")
        self.assertEqual(smyk[0].lowest_30d, "289 zł")
        self.assertEqual(smyk[0].discount_pct, 45)

        ross = monitor_okazji.parse_rossmann_page(SAMPLE_ROSSMANN, "Rossmann.pl")
        self.assertEqual(len(ross), 1)
        self.assertEqual(ross[0].price, "64,99 zł")
        self.assertEqual(ross[0].lowest_30d, "79,99 zł")
        self.assertGreaterEqual(ross[0].discount_pct, 35)

        casto = monitor_okazji.parse_castorama_page(SAMPLE_CASTORAMA, "Castorama.pl")
        self.assertEqual(len(casto), 1)
        self.assertEqual(casto[0].price, "86,98 zł")
        self.assertEqual(casto[0].old_price, "108 zł")

        bg = monitor_okazji.parse_biedronka_gazetki_page(
            SAMPLE_BIEDRONKA_GAZETKI, "Biedronka.pl (Gazetki)"
        )
        self.assertEqual(len(bg), 1)
        self.assertTrue(bg[0].is_leaflet)

    def test_ceneo_search_url_uses_clean_query(self) -> None:
        url = monitor_okazji.build_ceneo_search_url(
            "Słuchawki Google Pixel Buds 2a | wszystkie kolory za 360,82 zł"
        )
        self.assertTrue(url.startswith("https://www.ceneo.pl/;szukaj-"))
        self.assertIn("+", url)
        self.assertNotIn("360", url)

    def test_parse_atom(self) -> None:
        deals = monitor_okazji.parse_feed(SAMPLE_ATOM, "AtomSource")
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].link, "https://example.com/laptop")

    def test_keyword_filtering(self) -> None:
        deals = monitor_okazji.parse_feed(SAMPLE_RSS, "Pepper.pl")
        self.assertTrue(monitor_okazji.matches_filters(deals[0], ["amazon"], []))
        self.assertFalse(monitor_okazji.matches_filters(deals[1], ["ssd"], []))

    def test_run_monitor_deduplicates_and_tracks_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {"name": "Pepper.pl", "url": "https://example.test/rss", "type": "rss", "enabled": True}
                        ],
                        "keywords": ["ssd", "lego"],
                        "exclude_keywords": [],
                        "max_items_per_source": 10,
                        "auto_compare_top_n": 0,
                        "macos_notifications": False,
                        "report_file": "raport.md",
                        "csv_file": "historia.csv",
                        "seen_file": "seen.json",
                        "cache_file": "latest.json",
                        "price_history_file": "price_history.json",
                    }
                ),
                encoding="utf-8",
            )

            with patch("monitor_okazji.fetch_feed", return_value=SAMPLE_RSS):
                rc1 = monitor_okazji.run_monitor(cfg_path)
                self.assertEqual(rc1, 0)
                report1 = (tmp / "raport.md").read_text(encoding="utf-8")
                self.assertIn("Zestaw LEGO Star Wars", report1)
                self.assertIn("-50%", report1)
                cache1 = json.loads((tmp / "latest.json").read_text(encoding="utf-8"))
                self.assertEqual(cache1["deals"][0]["deal_id"], "pepper-2")
                self.assertTrue(cache1["deals"][0]["ceneo_url"].startswith("https://www.ceneo.pl/;szukaj-"))

                rc2 = monitor_okazji.run_monitor(cfg_path)
                self.assertEqual(rc2, 0)
                report2 = (tmp / "raport.md").read_text(encoding="utf-8")
                self.assertIn("Brak nowych okazji", report2)


if __name__ == "__main__":
    unittest.main()
