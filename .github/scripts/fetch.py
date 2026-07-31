#!/usr/bin/env python3
"""
DevPulse — Trend Radar for Content Farm.
Every 6 hours: finds trending repos, writes concise briefs.
The content farm (tech-tools-hub) reads these to enrich its articles.
"""
import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

API_KEY = os.environ["DEEPSEEK_API_KEY"]
RADAR_FILE = Path("trends.json")

# ══════════════════════════════════════════════════════════
# STEP 1: Find trending repos
# ══════════════════════════════════════════════════════════
def fetch_trending():
    print("🔍 Finding trending repos via GitHub Search API...")
    repos = []
    queries = [
        "stars:>50 created:>=2026-06-01",
        "stars:>100 pushed:>=2026-07-15",
    ]
    for q in queries:
        try:
            url = f"https://api.github.com/search/repositories?q={quote(q)}&sort=stars&order=desc&per_page=5"
            req = Request(url, headers={"User-Agent": "DevPulse/2.0", "Accept": "application/vnd.github+json"})
            data = json.loads(urlopen(req, timeout=15).read())
            for item in data.get("items", []):
                repos.append({
                    "name": item["full_name"],
                    "desc": (item.get("description") or "")[:200],
                    "stars": item["stargazers_count"],
                    "lang": item.get("language", ""),
                    "url": item["html_url"],
                    "topics": item.get("topics", [])[:5],
                })
            time.sleep(1)
        except Exception as e:
            print(f"  ⚠️ {e}")

    seen = set(); unique = []
    for r in repos:
        if r["name"] not in seen:
            seen.add(r["name"]); unique.append(r)
    unique.sort(key=lambda x: x["stars"], reverse=True)
    print(f"  Found {len(unique)} repos")
    return unique[:8]

# ══════════════════════════════════════════════════════════
# STEP 2: DeepSeek → 1-sentence trend briefs
# ══════════════════════════════════════════════════════════
def summarize(repos):
    if not repos: return []
    names = "\n".join([f"{i+1}. {r['name']} ({r['stars']}⭐) — {r['desc'][:100]}" for i,r in enumerate(repos)])
    prompt = f"""Below are today's trending open-source repos. For each, write:

1. A 1-sentence summary of what it does (plain English)
2. A 1-sentence "why it's trending" insight
3. Which Amazon product category naturally fits this topic (e.g. "programming books", "mechanical keyboards", "noise-cancelling headphones", "external monitors", "webcams", "standing desks", "AI/ML books")

Repos:
{names}

Return valid JSON array:
[{{"repo":"owner/name","what":"…","why":"…","affinity":"product category"}}]"""

    try:
        body = json.dumps({
            "model":"deepseek-chat","messages":[{"role":"user","content":prompt}],
            "max_tokens":1500,"temperature":0.4
        }).encode()
        req = Request("https://api.deepseek.com/chat/completions", data=body,
                      headers={"Authorization":f"Bearer {API_KEY}","Content-Type":"application/json"})
        resp = json.loads(urlopen(req, timeout=60).read())
        raw = resp["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json","").replace("```","").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  ⚠️ Summarize failed: {e}")
        return []

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    print("=" * 50)
    print("  📡 DevPulse Trend Radar")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    repos = fetch_trending()
    if not repos:
        print("No repos found. Skipping.")
        return

    briefs = summarize(repos)
    if not briefs:
        print("Summarization failed. Saving raw repos.")
        briefs = [{"repo":r["name"],"what":r["desc"],"why":"Trending on GitHub","affinity":"programming books"} for r in repos]

    # Merge stars back into briefs
    for b in briefs:
        match = next((r for r in repos if r["name"] == b.get("repo","")), None)
        if match:
            b["stars"] = match["stars"]
            b["lang"] = match["lang"]
            b["url"] = match["url"]

    radar = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "trends": briefs,
    }
    RADAR_FILE.write_text(json.dumps(radar, indent=2, ensure_ascii=False))
    print(f"✅ trends.json written ({len(briefs)} trends)")

    # Also generate a human-readable markdown
    md = f"# 📡 Tech Trends — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
    for b in briefs:
        md += f"### [{b.get('repo','')}]({b.get('url','')}) ⭐{b.get('stars','?')}\n"
        md += f"- **What**: {b.get('what','')}\n"
        md += f"- **Why trending**: {b.get('why','')}\n"
        md += f"- **Affinity**: {b.get('affinity','')}\n\n"
    Path("trends.md").write_text(md)
    print("✅ trends.md written")

    # Short status
    print(f"\n📊 Top trend: {briefs[0]['repo']} ⭐{briefs[0].get('stars','?')}")
    print(f"   {briefs[0].get('what','')[:100]}")

if __name__ == "__main__":
    main()
