#!/usr/bin/env python3
"""Generate sitemap.xml from the site's real, indexable, canonical pages.

A page is included when it is an HTML page that
  * does not carry a noindex robots directive, and
  * declares a canonical URL on the production domain.
The canonical URL itself is used as the <loc>, so the sitemap can never disagree
with the pages. <lastmod> is written only when the page's last Git commit date is
known; nothing is invented when Git history is unavailable. changefreq and
priority are deliberately omitted.

Usage:
    python3 scripts/build_sitemap.py           # write sitemap.xml
    python3 scripts/build_sitemap.py --check   # exit 1 if sitemap.xml is out of date
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from pathlib import Path

SITE = "https://strativaenergy.com.au"
SKIP_DIRS = {".git", "partials", "reports", "node_modules", "google-apps-script", "scripts", "config", "assets"}
NOINDEX = re.compile(r'<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', re.I)
CANONICAL = re.compile(r'<link\b[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', re.I)


def pages(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.html")):
        rel = p.relative_to(root)
        if set(rel.parts[:-1]) & SKIP_DIRS or (rel.parent == Path(".") and p.name.startswith("google")):
            continue
        out.append(p)
    return out


def git_date(root: Path, path: Path) -> str | None:
    try:
        res = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(path.relative_to(root))],
                             cwd=root, capture_output=True, text=True, check=True)
        value = res.stdout.strip()
        return value or None
    except (OSError, subprocess.CalledProcessError):
        return None


def entries(root: Path) -> list[tuple[str, str | None]]:
    rows = []
    for p in pages(root):
        raw = p.read_text(encoding="utf-8", errors="replace")
        if NOINDEX.search(raw):
            continue
        m = CANONICAL.search(raw)
        if not m or not m.group(1).startswith(SITE + "/"):
            continue
        rows.append((m.group(1), git_date(root, p)))
    return sorted(rows, key=lambda r: (r[0] != SITE + "/", r[0]))


def render(rows: list[tuple[str, str | None]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in rows:
        out.append("  <url>")
        out.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            out.append(f"    <lastmod>{lastmod}</lastmod>")
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--check", action="store_true", help="fail if the set of URLs in sitemap.xml differs from the pages")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    target = root / "sitemap.xml"
    rows = entries(root)
    if args.check:
        current = locs(target.read_text(encoding="utf-8")) if target.exists() else []
        expected = [r[0] for r in rows]
        if current != expected:
            print("sitemap.xml is out of date.\n  expected:", expected, "\n  found:   ", current)
            return 1
        print(f"sitemap.xml matches {len(expected)} indexable page(s).")
        return 0
    target.write_text(render(rows), encoding="utf-8")
    print(f"Wrote sitemap.xml with {len(rows)} URL(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
