#!/usr/bin/env python3
"""Generate static GitHub Pages bundle (docs/) for Monitor Okazji by Luis."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import monitor_okazji
import web_app


def build_static_site(project_dir: Path, out_dir: Path) -> int:
    """Fetch sources, update history files, and emit static HTML/JSON/PWA assets into out_dir."""
    config_path = project_dir / "config.json"
    config = monitor_okazji.load_config(config_path)

    seen_path = project_dir / config.get("seen_file", "seen_deals.json")
    history_path = project_dir / config.get("price_history_file", "price_history.json")
    cache_path = project_dir / config.get("cache_file", "latest_deals.json")

    seen_ids = monitor_okazji.load_seen_ids(seen_path)
    all_deals, errors = monitor_okazji.fetch_all_sources(config)
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    all_deals = monitor_okazji.update_and_attach_price_history(history_path, all_deals, timestamp)

    new_deals = [d for d in all_deals if d.deal_id not in seen_ids]
    for d in new_deals:
        seen_ids.add(d.deal_id)

    monitor_okazji.save_seen_ids(seen_path, seen_ids)
    monitor_okazji.save_latest_cache(cache_path, all_deals, errors, timestamp)

    # Optional free push notifications via ntfy.sh (skip macOS osascript in cloud/Linux)
    cloud_config = dict(config)
    cloud_config["macos_notifications"] = False
    monitor_okazji.send_notifications(new_deals, cloud_config)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": timestamp,
        "deals": [dataclasses.asdict(d) for d in all_deals],
        "errors": errors,
        "config": {
            "keywords": config.get("keywords", []),
            "sources": config.get("sources", []),
        },
    }
    (out_dir / "deals.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "icon.svg").write_text(web_app.ICON_SVG, encoding="utf-8")

    static_manifest = dict(web_app.MANIFEST_JSON)
    static_manifest["start_url"] = "./"
    static_manifest["icons"] = [{"src": "./icon.svg", "sizes": "any", "type": "image/svg+xml"}]
    (out_dir / "manifest.json").write_text(
        json.dumps(static_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Adapt web_app HTML_PAGE to work cleanly as a static GitHub Pages site
    static_html = web_app.HTML_PAGE
    static_html = static_html.replace('href="/manifest.json"', 'href="./manifest.json"')
    static_html = static_html.replace('href="/icon.svg"', 'href="./icon.svg"')
    static_html = static_html.replace(
        "await loadConfig();\n      const res = await fetch('/api/deals');\n      const data = await res.json();",
        "const res = await fetch('./deals.json?_=' + Date.now());\n      const data = await res.json();\n      if (data.config) {\n        currentConfig = data.config;\n        document.getElementById('keywordsInput').value = (currentConfig.keywords || []).join(', ');\n        const box = document.getElementById('sourcesCheckboxes');\n        box.innerHTML = (currentConfig.sources || []).map((s, idx) => `\n          <label><input type=\"checkbox\" data-source-idx=\"${idx}\" ${s.enabled ? 'checked' : ''} onchange=\"renderDeals()\" /> ${escapeHtml(s.name)}</label>\n        `).join('');\n      }",
    )
    static_html = static_html.replace(
        "fetch('/api/scan', { method: 'POST' })",
        "fetch('./deals.json?_=' + Date.now())",
    )
    static_html = static_html.replace(
        "<button onclick=\"saveConfigAndScan()\">Zapisz filtry i skanuj</button>",
        "<button onclick=\"applyStaticFilters()\">Zastosuj filtry</button>",
    )
    static_html = static_html.replace(
        "function clearFilters() {",
        "function applyStaticFilters() {\n      const raw = document.getElementById('keywordsInput').value;\n      currentConfig.keywords = raw.split(',').map(k => k.trim()).filter(Boolean);\n      const cbs = document.querySelectorAll('#sourcesCheckboxes input[type=\"checkbox\"]');\n      cbs.forEach(cb => { const i = Number(cb.dataset.sourceIdx); if (currentConfig.sources[i]) currentConfig.sources[i].enabled = cb.checked; });\n      renderDeals();\n    }\n    function clearFilters() {",
    )
    static_html = static_html.replace(
        "let filtered = modeFilteredDeals().filter(d => {",
        "const enabledSet = new Set((currentConfig.sources || []).filter(s => s.enabled).map(s => s.name));\n      const kwList = (currentConfig.keywords || []).map(k => k.toLowerCase());\n      let filtered = modeFilteredDeals().filter(d => {\n        if (enabledSet.size > 0 && !enabledSet.has(d.source)) return false;\n        if (kwList.length > 0) {\n          const hay = [d.title, d.summary, d.merchant, d.category].filter(Boolean).join(' ').toLowerCase();\n          if (!kwList.some(k => hay.includes(k))) return false;\n        }",
    )
    (out_dir / "index.html").write_text(static_html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Zbudowano statyczny dashboard w {out_dir} ({len(all_deals)} pozycji).")
    return 0


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    raise SystemExit(build_static_site(root, root / "docs"))
