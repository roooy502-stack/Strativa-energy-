#!/usr/bin/env python3
"""Deterministic SEO optimizer for review-before-publish workflows.

The optimizer only keeps social metadata consistent with each page and rebuilds the sitemap. It
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

SKIP_DIRS = {".git", "partials", "reports", "node_modules", "google-apps-script", "scripts", "config", "assets"}


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
    anchor = re.search(r"<script type=\"application/ld\+json\">|</head>", html_text, re.IGNORECASE)
    if not anchor:
        raise ValueError("page does not contain </head>")
    return html_text[:anchor.start()] + replacement + "\n" + html_text[anchor.start():], True


def is_indexable(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return not re.search(r'<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', text, re.I)


def published_pages(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.html")):
        rel = p.relative_to(root)
        if set(rel.parts[:-1]) & SKIP_DIRS or (rel.parent == Path(".") and p.name.startswith("google")):
            continue
        if is_indexable(p):
            out.append(p)
    return out


def page_text(html_text: str) -> tuple[str, str]:
    title = re.search(r"<title\b[^>]*>(.*?)</title>", html_text, re.I | re.S)
    desc = re.search(r'<meta\b[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)', html_text, re.I)
    return (html.unescape(title.group(1).strip()) if title else "", html.unescape(desc.group(1)) if desc else "")


def optimize(root: Path, targets: dict) -> list[str]:
    """Keep Open Graph and Twitter titles/descriptions in step with each page's own
    <title> and meta description, then rebuild the sitemap. Page copy is never rewritten."""
    changes: list[str] = []
    for path in published_pages(root):
        original = path.read_text(encoding="utf-8")
        title, desc = page_text(original)
        if not title or not desc:
            continue
        updated = original
        for key, value in (("og:title", title), ("og:description", desc), ("twitter:title", title), ("twitter:description", desc)):
            attr = "property" if key.startswith("og:") else "name"
            updated, changed = replace_or_insert_meta(updated, attr=attr, key=key, value=value)
            if changed:
                changes.append(f"{path.relative_to(root).as_posix()}: synced {key}")
        if updated != original:
            path.write_text(updated, encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_sitemap  # noqa: E402
    sitemap = root / "sitemap.xml"
    old = sitemap.read_text(encoding="utf-8") if sitemap.exists() else ""
    new = build_sitemap.render(build_sitemap.entries(root))
    if build_sitemap.locs(old) != build_sitemap.locs(new):
        sitemap.write_text(new, encoding="utf-8")
        changes.append("Rebuilt sitemap from indexable canonical pages")
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
