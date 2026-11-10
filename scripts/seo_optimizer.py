#!/usr/bin/env python3
"""Deterministic SEO optimizer for review-before-publish workflows.

The optimizer only applies evidence-backed metadata and sitemap changes. It
never edits files in dry-run mode and always creates a review branch before
writing changes when --apply is selected.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

TITLE = "Strativa Energy | Australian Solar & BESS Development"
DESCRIPTION = "Strativa Energy supports international developers entering Australia and progressing utility-scale solar and battery energy storage projects."


def run(cmd: list[str], cwd: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=capture)


def git_output(cmd: list[str], cwd: Path) -> str:
    return run(["git", *cmd], cwd, capture=True).stdout.strip()


def replace_or_insert_meta(html_text: str, *, attr: str, key: str, value: str) -> tuple[str, bool]:
    escaped = html.escape(value, quote=True)
    pattern = re.compile(
        rf"<meta(?=[^>]*\b{re.escape(attr)}=[\"']{re.escape(key)}[\"'])[^>]*>",
        re.IGNORECASE,
    )
    replacement = f'<meta {attr}="{key}" content="{escaped}">'
    updated, count = pattern.subn(replacement, html_text, count=1)
    if count:
        return updated, updated != html_text
    head = re.search(r"</head>", html_text, re.IGNORECASE)
    if not head:
        raise ValueError("index.html does not contain </head>")
    return html_text[:head.start()] + "  " + replacement + "\n" + html_text[head.start():], True


def replace_title(html_text: str) -> tuple[str, bool]:
    replacement = f"<title>{html.escape(TITLE)}</title>"
    updated, count = re.subn(r"<title\b[^>]*>.*?</title>", replacement, html_text, count=1, flags=re.IGNORECASE | re.DOTALL)
    if not count:
        head = re.search(r"</head>", html_text, re.IGNORECASE)
        if not head:
            raise ValueError("index.html does not contain </head>")
        return html_text[:head.start()] + "  " + replacement + "\n" + html_text[head.start():], True
    return updated, updated != html_text


def is_indexable(path: Path, root: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return not re.search(r'<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', text, re.I)


def published_pages(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.html")
        if ".git" not in p.parts and p.name != "google743f94c5d2ad6d26.html" and is_indexable(p, root)
    )


def sitemap_text(root: Path, canonical: str, existing: str) -> str:
    pages = published_pages(root)
    rows: list[str] = []
    expected: list[str] = []
    for path in pages:
        loc = canonical if path.name == "index.html" else urljoin(canonical, path.relative_to(root).as_posix())
        expected.append(loc)
        rows.append("  <url>\n    <loc>" + html.escape(loc) + "</loc>\n  </url>")
    current = re.findall(r"<loc>\s*([^<]+)\s*</loc>", existing)
    if current == expected:
        return existing
    generated = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n\n'
    generated += "\n\n".join(rows)
    generated += "\n\n</urlset>\n"
    return generated


def optimize(root: Path, targets: dict) -> list[str]:
    site = targets.get("site", {}).get("url", "https://strativaenergy.com.au/")
    canonical = site.rstrip("/") + "/"
    index = root / "index.html"
    if not index.exists():
        raise FileNotFoundError("index.html not found")
    original = index.read_text(encoding="utf-8")
    updated, changed = replace_title(original)
    changes = ["Updated homepage title"] if changed else []
    updated, changed = replace_or_insert_meta(updated, attr="name", key="description", value=DESCRIPTION)
    if changed:
        changes.append("Updated homepage meta description")
    confirmed = {
        "og:type": "website",
        "og:url": canonical,
        "og:title": TITLE,
        "og:description": DESCRIPTION,
        "og:image": urljoin(canonical, "assets/hero.webp"),
        "twitter:card": "summary_large_image",
        "twitter:title": TITLE,
        "twitter:description": DESCRIPTION,
        "twitter:image": urljoin(canonical, "assets/hero.webp"),
    }
    for key, value in confirmed.items():
        attr = "property" if key.startswith("og:") else "name"
        updated, changed = replace_or_insert_meta(updated, attr=attr, key=key, value=value)
        if changed:
            changes.append(f"Updated {key}")
    if not (root / "assets/hero.webp").is_file():
        raise FileNotFoundError("assets/hero.webp is required for social metadata")
    if updated != original:
        index.write_text(updated, encoding="utf-8")

    sitemap = root / "sitemap.xml"
    if not sitemap.exists():
        raise FileNotFoundError("sitemap.xml not found")
    old_sitemap = sitemap.read_text(encoding="utf-8")
    new_sitemap = sitemap_text(root, canonical, old_sitemap)
    if new_sitemap != old_sitemap:
        sitemap.write_text(new_sitemap, encoding="utf-8")
        changes.append("Rebuilt sitemap from published indexable HTML pages")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--audit", default="reports/seo-audit-latest.json")
    ap.add_argument("--apply", action="store_true", help="Create a review branch, then apply safe changes")
    ap.add_argument("--dry-run", action="store_true", help="Read and report only; never change files or Git state")
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
    dirty_lines = run(["git", "status", "--porcelain"], root, capture=True).stdout.splitlines()
    allowed_prefixes = ("reports/seo-audit-latest.json", "reports/seo-audit-latest.md", "scripts/__pycache__/", "__pycache__/")
    unexpected = [line for line in dirty_lines if not line[3:].strip().startswith(allowed_prefixes)]
    if unexpected:
        raise SystemExit("Refusing to apply changes: working tree has uncommitted source changes.")
    original_branch = git_output(["branch", "--show-current"], root) or "main"
    branch = "seo-auto/review-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run(["git", "checkout", "-b", branch], root)
    try:
        changes = optimize(root, targets)
    except Exception:
        run(["git", "checkout", original_branch], root)
        run(["git", "branch", "-D", branch], root)
        raise
    if not changes:
        run(["git", "checkout", original_branch], root)
        run(["git", "branch", "-D", branch], root)
        print("No safe deterministic changes needed; no branch retained.")
        return 0
    print(json.dumps({"branch": branch, "changes": changes}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"SEO optimizer failed: {exc}", file=sys.stderr)
        sys.exit(1)
