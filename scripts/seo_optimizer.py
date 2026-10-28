#!/usr/bin/env python3
"""Review-before-publish optimizer.

Only deterministic metadata additions and sitemap maintenance are allowed.
The script never edits main directly, never merges, and never creates FAQ
content or unsupported claims.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def add_meta(html: str, tag: str, marker: str) -> tuple[str, bool]:
    if marker.lower() in html.lower():
        return html, False
    pos = html.lower().find("</head>")
    if pos < 0:
        return html, False
    return html[:pos] + "  " + tag + "\n" + html[pos:], True


def optimize(root: Path, targets: dict) -> list[str]:
    site = targets.get("site", {}).get("url", "https://strativaenergy.com.au/")
    index = root / "index.html"
    html = index.read_text(encoding="utf-8")
    changes: list[str] = []
    canonical = site.rstrip("/") + "/"
    if "rel=\"canonical\"" not in html.lower() and "rel='canonical'" not in html.lower():
        html, changed = add_meta(html, f'<link rel="canonical" href="{canonical}">', "rel=\"canonical\"")
        if changed: changes.append("Added canonical URL")
    if not re.search(r'<meta\s+[^>]*name=["\']robots["\']', html, re.I):
        html, changed = add_meta(html, '<meta name="robots" content="index, follow">', 'name="robots"')
        if changed: changes.append("Added robots meta")
    confirmed = {
        "og:type": "website", "og:url": canonical,
        "og:title": "Strativa Energy | Australia Market Entry & Development Support",
        "og:description": "Australian development support for international developers entering and progressing utility-scale solar and BESS projects in Australia.",
        "og:image": urljoin(canonical, "assets/hero.webp"),
        "twitter:card": "summary_large_image",
        "twitter:title": "Strativa Energy | Australia Market Entry & Development Support",
        "twitter:description": "Australian development support for international developers entering and progressing utility-scale solar and BESS projects in Australia.",
        "twitter:image": urljoin(canonical, "assets/hero.webp")
    }
    for key, value in confirmed.items():
        attr = "property" if key.startswith("og:") else "name"
        marker = f'{attr}="{key}"'
        html, changed = add_meta(html, f'<meta {attr}="{key}" content="{value}">', marker)
        if changed: changes.append(f"Added {key}")
    if changes:
        index.write_text(html, encoding="utf-8")
    sitemap = root / "sitemap.xml"
    if sitemap.exists():
        old = sitemap.read_text(encoding="utf-8")
        pages = []
        for p in sorted(root.rglob("*.html")):
            if p.name == "google743f94c5d2ad6d26.html": continue
            pages.append(canonical if p.name == "index.html" else urljoin(canonical, p.relative_to(root).as_posix()))
        existing = set(re.findall(r"<loc>\s*([^<]+)\s*</loc>", old))
        missing = [p for p in pages if p not in existing]
        if missing:
            inserts = "\n".join(f"  <url>\n    <loc>{p}</loc>\n  </url>" for p in missing)
            sitemap.write_text(old.replace("</urlset>", inserts + "\n</urlset>"), encoding="utf-8")
            changes.append("Updated sitemap with confirmed HTML pages")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--audit", default="reports/seo-audit-latest.json")
    ap.add_argument("--apply", action="store_true", help="Apply safe additions and create a review branch")
    ap.add_argument("--dry-run", action="store_true", help="Explicitly select the no-change dry-run mode")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    targets = json.loads((root / "config/seo_targets.json").read_text(encoding="utf-8"))
    audit_path = root / args.audit
    if not audit_path.exists():
        raise SystemExit("Audit report not found; run seo_audit.py first.")
    result = json.loads(audit_path.read_text(encoding="utf-8"))
    print(f"Audit issues: {len(result.get('errors', []))}; opportunities: {len(result.get('improvement_opportunities', []))}")
    if args.dry_run or not args.apply:
        print("Dry run: no files changed, no branch created, and no pull request created.")
        return 0
    changes = optimize(root, targets)
    if not changes:
        print("No safe deterministic changes needed; no branch or pull request created.")
        return 0
    branch = "seo-auto/review-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run(["git", "checkout", "-b", branch], root)
    print(json.dumps({"branch": branch, "changes": changes}, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
