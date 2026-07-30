#!/usr/bin/env python3
"""
DevPulse — Tech Stack Trending Tracker.
Runs every 6 hours via GitHub Actions.
Fetches GitHub trending repos, NPM/PyPI download stats → free JSON API.
"""
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")

# ── GITHUB TRENDING ──────────────────────────────────────
def fetch_github_trending() -> list[dict]:
    """Fetch trending repos from GitHub trending page (HTML parse)."""
    url = "https://github.com/trending?since=daily"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        req = Request(url, headers=headers)
        html = urlopen(req, timeout=15).read().decode("utf-8", errors="replace")

        repos = []
        # Parse trending repo blocks
        blocks = re.findall(r'<article[^>]*class="Box-row"[^>]*>(.*?)</article>', html, re.DOTALL)
        for block in blocks[:10]:
            # Repo name: owner / name
            name_match = re.search(r'/([^/"]+)/([^/"]+)"', block)
            if not name_match:
                continue
            owner, repo_name = name_match.group(1), name_match.group(2)
            full_name = f"{owner}/{repo_name}"

            # Description
            desc_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*[^>]*>(.*?)</p>', block, re.DOTALL)
            desc = desc_match.group(1).strip() if desc_match else ""
            desc = re.sub(r'<[^>]+>', '', desc).strip()

            # Language
            lang_match = re.search(r'itemprop="programmingLanguage"[^>]*>([^<]+)<', block)
            language = lang_match.group(1).strip() if lang_match else "Unknown"

            # Stars today
            stars_match = re.search(r'(\d[\d,]*)\s+stars\s+today', block)
            stars_today = int(stars_match.group(1).replace(",", "")) if stars_match else 0

            # Total stars
            total_match = re.search(r'(\d[\d,]*)\s+stars', block)
            total_stars = int(total_match.group(1).replace(",", "")) if total_match else 0

            repos.append({
                "repo": full_name,
                "description": desc,
                "language": language,
                "stars_total": total_stars,
                "stars_today": stars_today,
                "url": f"https://github.com/{full_name}",
            })
        return repos
    except Exception as e:
        print(f"   ⚠️ GitHub trending failed: {e}")
        return []


# ── NPM DOWNLOADS ────────────────────────────────────────
TOP_NPM_PACKAGES = [
    "react", "next", "vue", "tailwindcss", "typescript",
    "vite", "esbuild", "astro", "svelte", "zod",
]

def fetch_npm_downloads(pkg: str) -> dict:
    """Fetch weekly downloads for an NPM package."""
    url = f"https://api.npmjs.org/downloads/point/last-week/{pkg}"
    try:
        req = Request(url, headers={"User-Agent": "DevPulse/1.0"})
        data = json.loads(urlopen(req, timeout=10).read())
        return {
            "package": pkg,
            "downloads_week": data.get("downloads", 0),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"package": pkg, "downloads_week": None, "error": str(e)[:100]}


# ── PYPI DOWNLOADS ───────────────────────────────────────
TOP_PYPI_PACKAGES = [
    "numpy", "pandas", "fastapi", "pydantic", "langchain",
    "torch", "polars", "ruff", "uv", "httpx",
]

def fetch_pypi_downloads(pkg: str) -> dict:
    """Fetch monthly downloads for a PyPI package."""
    url = f"https://pypistats.org/api/packages/{pkg}/recent"
    try:
        req = Request(url, headers={"User-Agent": "DevPulse/1.0"})
        data = json.loads(urlopen(req, timeout=10).read())
        return {
            "package": pkg,
            "downloads_month": data.get("data", {}).get("last_month", 0) if "data" in data else 0,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"package": pkg, "downloads_month": None, "error": str(e)[:100]}


# ── STORAGE ──────────────────────────────────────────────
def save_json(filename: str, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"   💾 {filename}")


def append_history(filename: str, entry: dict):
    """Append a data point to a time-series JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    history = []
    if path.exists():
        with open(path) as f:
            history = json.load(f)

    # Strip to essentials
    history.append({k: v for k, v in entry.items() if k != "error"})

    # Keep 90 days
    max_entries = 360
    if len(history) > max_entries:
        history = history[-max_entries:]

    with open(path, "w") as f:
        json.dump(history, f, indent=2)


# ── REPORT ──────────────────────────────────────────────
def generate_report(trending: list, npm: list, pypi: list):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"trends-{today}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 📊 DevPulse Tech Trends — {today}",
        f"*Auto-generated at {datetime.now(timezone.utc).strftime('%H:%M UTC')}*",
        "",
        "## 🔥 GitHub Trending",
        "| # | Repo | Language | ⭐ Today | ⭐ Total |",
        "|---|------|----------|----------|----------|",
    ]
    for i, r in enumerate(trending[:10], 1):
        lines.append(f"| {i} | [{r['repo']}]({r['url']}) | {r['language']} | +{r['stars_today']} | {r['stars_total']} |")

    lines += [
        "",
        "## 📦 NPM Weekly Downloads",
        "| Package | Downloads |",
        "|---------|-----------|",
    ]
    for p in sorted(npm, key=lambda x: x.get("downloads_week", 0) or 0, reverse=True):
        dl = f"{p.get('downloads_week', 'N/A'):,}" if p.get("downloads_week") else "N/A"
        lines.append(f"| {p['package']} | {dl} |")

    lines += [
        "",
        "## 🐍 PyPI Monthly Downloads",
        "| Package | Downloads |",
        "|---------|-----------|",
    ]
    for p in sorted(pypi, key=lambda x: x.get("downloads_month", 0) or 0, reverse=True):
        dl = f"{p.get('downloads_month', 'N/A'):,}" if p.get("downloads_month") else "N/A"
        lines.append(f"| {p['package']} | {dl} |")

    lines += [
        "",
        "---",
        "## 💎 Pro: Custom tech stack alerts",
        "Track any repo/package you care about. Get email alerts when trends shift.",
        "[→ Subscribe $3/mo](https://buymeacoffee.com/) *(Coming soon)*",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"📄 Report: {path}")


# ── MAIN ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  📊 DevPulse — Tech Stack Trends")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. GitHub Trending
    print("\n🔍 Fetching GitHub trending...")
    trending = fetch_github_trending()
    save_json("github_trending.json", {
        "updated": datetime.now(timezone.utc).isoformat(),
        "repos": trending,
    })
    for r in trending:
        append_history(f"gh_{r['repo'].replace('/', '_')}.json", {
            "t": datetime.now(timezone.utc).isoformat()[:19],
            "stars": r["stars_total"],
            "stars_today": r["stars_today"],
        })
    print(f"   Found {len(trending)} trending repos")

    # 2. NPM Stats
    print("\n📦 Fetching NPM download stats...")
    npm_stats = []
    for pkg in TOP_NPM_PACKAGES:
        data = fetch_npm_downloads(pkg)
        npm_stats.append(data)
        if data.get("downloads_week"):
            append_history(f"npm_{pkg}.json", {
                "t": datetime.now(timezone.utc).isoformat()[:19],
                "dl": data["downloads_week"],
            })
    save_json("npm_stats.json", {
        "updated": datetime.now(timezone.utc).isoformat(),
        "packages": npm_stats,
    })

    # 3. PyPI Stats
    print("\n🐍 Fetching PyPI download stats...")
    pypi_stats = []
    for pkg in TOP_PYPI_PACKAGES:
        data = fetch_pypi_downloads(pkg)
        pypi_stats.append(data)
        if data.get("downloads_month"):
            append_history(f"pypi_{pkg}.json", {
                "t": datetime.now(timezone.utc).isoformat()[:19],
                "dl": data["downloads_month"],
            })
    save_json("pypi_stats.json", {
        "updated": datetime.now(timezone.utc).isoformat(),
        "packages": pypi_stats,
    })

    # 4. Report
    generate_report(trending, npm_stats, pypi_stats)
    print(f"\n✨ Done. {len(trending)} trending + {len(npm_stats)} NPM + {len(pypi_stats)} PyPI")


if __name__ == "__main__":
    main()
