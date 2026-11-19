#!/usr/bin/env python3
"""Keep the shared head, header, footer and script blocks identical on every page.

Pages are plain, hand-editable HTML. The shared blocks live in partials/ and are
copied between marker comments, for example:

    <!-- layout:header:start --> ... <!-- layout:header:end -->

Usage:
    python3 scripts/sync_layout.py          # rewrite pages
    python3 scripts/sync_layout.py --check  # exit 1 if any page is out of sync (for CI)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BLOCKS = {"head": "head.html", "header": "header.html", "footer": "footer.html", "scripts": "scripts.html"}
SKIP_DIRS = {".git", "partials", "reports", "node_modules", "google-apps-script", "scripts", "config", "assets"}


def page_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.html")):
        rel = p.relative_to(root)
        if set(rel.parts[:-1]) & SKIP_DIRS or p.name.startswith("google") and p.name.endswith(".html") and rel.parent == Path("."):
            continue
        out.append(p)
    return out


def url_path(rel: Path) -> str:
    if rel.name == "index.html":
        parent = rel.parent.as_posix()
        return "/" if parent == "." else f"/{parent}/"
    if rel.name == "404.html":
        return "/404/"
    return "/" + rel.as_posix()


def is_current(link: str, page: str) -> bool:
    if link == "/":
        return page == "/"
    return page == link or page.startswith(link)


def render_header(template: str, page: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return ' aria-current="page"' if is_current(m.group(1), page) else ""
    return re.sub(r"\{\{cur:([^}]+)\}\}", repl, template)


def sync(root: Path, check: bool) -> int:
    partials = {k: (root / "partials" / v).read_text(encoding="utf-8").rstrip("\n") for k, v in BLOCKS.items()}
    stale = 0
    for path in page_files(root):
        text = path.read_text(encoding="utf-8")
        page = url_path(path.relative_to(root))
        new = text
        for name, body in partials.items():
            if name == "header":
                body = render_header(body, page)
            pat = re.compile(rf"(<!-- layout:{name}:start -->).*?(<!-- layout:{name}:end -->)", re.S)
            if not pat.search(new):
                print(f"WARNING: {path.relative_to(root)} has no layout:{name} markers", file=sys.stderr)
                stale += 1
                continue
            new = pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), new, count=1)
        if new != text:
            if check:
                print(f"Out of sync: {path.relative_to(root)}")
                stale += 1
            else:
                path.write_text(new, encoding="utf-8")
                print(f"Updated {path.relative_to(root)}")
    if check and stale:
        return 1
    if not check:
        print("Layout sync complete.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return sync(Path(args.repo_root).resolve(), args.check)


if __name__ == "__main__":
    sys.exit(main())
