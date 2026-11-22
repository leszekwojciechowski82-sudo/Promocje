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

SAMPLE_BLIX = """
<div class="page-wrapper" data-leaflet-id="537711" data-leaflet-name="Od poniedziałku" data-brand-name="Biedronka" data-brand-slug="biedronka" data-brand-logo="https://imgproxy.blix.pl/image/brand/thumbnail_23.jpg">
  <img src="https://imgproxy.blix.pl/image/leaflet/537711/page1.jpg" />
</div>
""".encode("utf-8")

SAMPLE_LIDL = """
<div data-grid-data="{&quot;productId&quot;: 100410059, &quot;fullTitle&quot;: &quot;ESMARA Koszula nocna&quot;, &quot;canonicalUrl&quot;: &quot;/p/esmara/p100410059&quot;, &quot;image&quot;: &quot;https://www.lidl.pl/assets/img.jpg&quot;, &quot;category&quot;: &quot;Moda&quot;, &quot;price&quot;: {&quot;price&quot;: 18.5, &quot;discount&quot;: {&quot;deletedPrice&quot;: 36.99, &quot;percentageDiscount&quot;: 49, &quot;absoluteDiscount&quot;: 18.49}}}"></div>
""".encode("utf-8")

SAMPLE_BIEDRONKA_HOME = """
<div class="product-tile" data-itemid="676597">
  <a href="https://home.biedronka.pl/robot-hoffen.html"></a>
  <img src="https://home.biedronka.pl/dw/image/v2/robot.jpg" alt="Robot planetarny Hoffen Expert" />
  <div class="product-tile__name">Robot planetarny Hoffen Expert 1500W</div>
  <span>-45%</span>
  <span>269 00 zł</span>
  <span>499 00 zł</span>
</div>
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

    def test_parse_lidl_and_biedronka_home(self) -> None:
        lidl_deals = monitor_okazji.parse_lidl_page(SAMPLE_LIDL, "Lidl.pl (Promocje)")
        self.assertEqual(len(lidl_deals), 1)
        self.assertEqual(lidl_deals[0].discount_pct, 49)
        self.assertEqual(lidl_deals[0].old_price, "36,99 zł")
        self.assertFalse(lidl_deals[0].is_leaflet)

        bh_deals = monitor_okazji.parse_biedronka_home_page(
            SAMPLE_BIEDRONKA_HOME, "Biedronka Home"
        )
        self.assertEqual(len(bh_deals), 1)
        self.assertEqual(bh_deals[0].price, "269 zł")
        self.assertEqual(bh_deals[0].old_price, "499 zł")
        self.assertGreaterEqual(bh_deals[0].discount_pct, 45)
        self.assertFalse(bh_deals[0].is_leaflet)

    def test_parse_blix_page(self) -> None:
        deals = monitor_okazji.parse_blix_page(
            SAMPLE_BLIX, "Blix: Biedronka", "https://blix.pl/sklep/biedronka/"
        )
        self.assertEqual(len(deals), 1)
        self.assertTrue(deals[0].is_leaflet)
        self.assertEqual(deals[0].merchant, "Biedronka")
        self.assertIn("537711", deals[0].link)

    def test_parse_atom(self) -> None:
        deals = monitor_okazji.parse_feed(SAMPLE_ATOM, "AtomSource")
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0].link, "https://example.com/laptop")

    def test_keyword_filtering(self) -> None:
        deals = monitor_okazji.parse_feed(SAMPLE_RSS, "Pepper.pl")
        self.assertTrue(monitor_okazji.matches_filters(deals[0], ["amazon"], []))
        self.assertFalse(monitor_okazji.matches_filters(deals[1], ["ssd"], []))
        self.assertFalse(monitor_okazji.matches_filters(deals[0], ["ssd"], ["nvme"]))

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
                self.assertTrue(len(cache1["deals"][0]["price_history"]) >= 2)

                rc2 = monitor_okazji.run_monitor(cfg_path)
                self.assertEqual(rc2, 0)
                report2 = (tmp / "raport.md").read_text(encoding="utf-8")
                self.assertIn("Brak nowych okazji", report2)


if __name__ == "__main__":
    unittest.main()
