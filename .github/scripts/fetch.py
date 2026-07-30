#!/usr/bin/env python3
"""
PriceWatch — Automated Amazon price tracker.
Runs every 6 hours via GitHub Actions.
Grabs prices for configured ASINs, stores history, generates reports.
"""
import json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
CONFIG_FILE = Path("config.json")


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


# ── PRICE FETCHING ───────────────────────────────────────
def fetch_amazon_price(asin: str) -> dict:
    """Fetch price from Amazon product page. No API key needed."""
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
        "Cache-Control": "no-cache",
    }
    try:
        req = Request(url, headers=headers)
        html = urlopen(req, timeout=15).read().decode("utf-8", errors="replace")

        # Try multiple price extraction patterns
        # Pattern 1: whole price in span
        price_match = re.search(r'<span[^>]*class="a-price[^"]*"[^>]*>.*?<span[^>]*class="a-offscreen"[^>]*>\$([\d,.]+)</span>', html, re.DOTALL)
        if not price_match:
            # Pattern 2: price in script data
            price_match = re.search(r'"price"\s*:\s*"?\$?([\d,.]+)"?', html)
        if not price_match:
            # Pattern 3: any $XX.XX pattern near the buy box
            price_match = re.search(r'data-asin-price="([\d,.]+)"', html)

        price = float(price_match.group(1).replace(",", "")) if price_match else None

        # Product title
        title_match = re.search(r'<span[^>]*id="productTitle"[^>]*>(.*?)</span>', html, re.DOTALL)
        title = title_match.group(1).strip() if title_match else None

        return {
            "asin": asin,
            "price": price,
            "currency": "USD",
            "title": title,
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "asin": asin,
            "price": None,
            "currency": "USD",
            "error": str(e)[:200],
            "url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


# ── HISTORY STORAGE ──────────────────────────────────────
def save_price_history(product_id: str, entry: dict):
    """Append a price data point to the product's JSON history file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history_file = DATA_DIR / f"{product_id}.json"

    history = []
    if history_file.exists():
        with open(history_file) as f:
            history = json.load(f)

    # Keep only timestamp + price to save space
    history.append({
        "t": entry["fetched_at"][:19],
        "p": entry["price"],
    })

    # Keep last 90 days (~360 data points for 6-hour interval)
    history = history[-360:]

    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)

    print(f"   📦 {product_id}: ${entry['price']} ({len(history)} data points)")


# ── COMPETITIVE REPORT ────────────────────────────────────
def generate_report(config: dict, all_prices: list[dict]):
    """Generate a competitive price report markdown file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_file = REPORTS_DIR / f"report-{today}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 📊 PriceWatch Report — {today}",
        f"*Auto-generated at {datetime.now(timezone.utc).strftime('%H:%M UTC')}*",
        "",
        "## Summary",
        f"| Product | Price | Competitor Low | vs Competitor |",
        f"|---------|-------|---------------|---------------|",
    ]

    for prod in config["products"]:
        prod_entry = next((e for e in all_prices if e["asin"] == prod["asin"]), {})
        prod_price = prod_entry.get("price")

        # Find competitor prices
        competitor_low = None
        competitor_details = []
        for comp in prod.get("competitors", []):
            comp_entry = next((e for e in all_prices if e["asin"] == comp["asin"]), {})
            comp_price = comp_entry.get("price")
            if comp_price:
                competitor_details.append(f"{comp['name']}: ${comp_price}")
                if competitor_low is None or comp_price < competitor_low:
                    competitor_low = comp_price

        prod_price_str = f"${prod_price}" if prod_price else "N/A"
        comp_low_str = f"${competitor_low}" if competitor_low else "N/A"

        if prod_price and competitor_low:
            diff_pct = round((prod_price - competitor_low) / competitor_low * 100, 1)
            diff_str = f"{'+' if diff_pct > 0 else ''}{diff_pct}%"
        else:
            diff_str = "N/A"

        lines.append(f"| {prod['name']} | {prod_price_str} | {comp_low_str} | {diff_str} |")

    lines.append("")
    lines.append("## Detail")
    lines.append("")
    for prod in config["products"]:
        lines.append(f"### {prod['name']}")
        lines.append(f"[Amazon]({prod['url']})")
        prod_entry = next((e for e in all_prices if e["asin"] == prod["asin"]), {})
        lines.append(f"- Target: ${prod_entry.get('price', 'N/A')}")
        lines.append("- Competitors:")
        for comp in prod.get("competitors", []):
            comp_entry = next((e for e in all_prices if e["asin"] == comp["asin"]), {})
            lines.append(f"  - {comp['name']}: ${comp_entry.get('price', 'N/A')}")
        lines.append("")

    lines.append("---")
    lines.append("[Get custom price alerts →](https://buymeacoffee.com/) *(Coming soon)*")

    with open(report_file, "w") as f:
        f.write("\n".join(lines))

    print(f"\n📄 Report: {report_file}")


# ── MAIN ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  💰 PriceWatch — Amazon Price Tracker")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    config = load_config()
    all_prices = []

    for prod in config["products"]:
        print(f"\n🔍 Fetching: {prod['name']} ({prod['asin']})...")
        entry = fetch_amazon_price(prod["asin"])
        if entry["price"]:
            save_price_history(prod["id"], entry)
        else:
            print(f"   ⚠️  Failed: {entry.get('error', 'unknown error')}")
        all_prices.append(entry)

        # Fetch competitors
        for comp in prod.get("competitors", []):
            print(f"   ↳ Competitor: {comp['name']} ({comp['asin']})...")
            comp_entry = fetch_amazon_price(comp["asin"])
            if comp_entry["price"]:
                save_price_history(comp["asin"], comp_entry)
            else:
                print(f"      ⚠️  Failed: {comp_entry.get('error', 'unknown error')}")
            all_prices.append(comp_entry)

        # Be nice to Amazon
        time.sleep(2)

    generate_report(config, all_prices)
    print(f"\n✨ Done. {len(all_prices)} price points fetched.")


if __name__ == "__main__":
    main()
