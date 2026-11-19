#!/usr/bin/env python3
"""Static SEO/AEO/GEO audit for the Strativa Energy website."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_SITE_URL = "https://strativaenergy.com.au/"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.headings: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.jsonld: list[str] = []
        self.visible_chunks: list[str] = []
        self._in_title = False
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self._in_jsonld = False
        self._jsonld_buffer: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = tag
            self._heading_text = []
        if tag == "meta":
            self.meta.append(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs)
        if tag == "img":
            self.images.append(attrs)
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._heading == tag:
            self.headings.append((tag, " ".join(self._heading_text).strip()))
            self._heading = None
        if tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._jsonld_buffer).strip())
            self._in_jsonld = False
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._jsonld_buffer.append(data)
        if self._heading is not None:
            self._heading_text.append(data)
        if not self._skip_depth and data.strip():
            self.visible_chunks.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self.visible_chunks)


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser


def meta_value(parser: PageParser, *, name: str | None = None, prop: str | None = None) -> str | None:
    for item in parser.meta:
        if name and item.get("name", "").lower() == name.lower():
            return item.get("content", "")
        if prop and item.get("property", "").lower() == prop.lower():
            return item.get("content", "")
    return None


def canonical_value(raw: str) -> str | None:
    patterns = [
        r"<link\b[^>]*\brel=[\"']canonical[\"'][^>]*\bhref=[\"']([^\"']+)",
        r"<link\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*\brel=[\"']canonical[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            return match.group(1)
    return None


def schema_types(parser: PageParser) -> tuple[list[str], list[str]]:
    types: list[str] = []
    invalid: list[str] = []
    for raw in parser.jsonld:
        try:
            value = json.loads(raw)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, dict):
                    item_types = item.get("@type", [])
                    if isinstance(item_types, str):
                        item_types = [item_types]
                    types.extend(str(x) for x in item_types)
        except json.JSONDecodeError:
            invalid.append(raw[:120])
    return sorted(set(types)), invalid


def internal_reference(href: str, page_rel: str) -> tuple[str, str | None] | None:
    if href.startswith(("mailto:", "tel:", "data:", "javascript:")):
        return None
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = parsed.path
    if raw_path:
        base = Path(page_rel).parent
        target = (base / raw_path).as_posix() if not raw_path.startswith("/") else raw_path.lstrip("/")
    else:
        target = page_rel
    target = target or "index.html"
    if target.endswith("/"):
        target += "index.html"
    return target.lstrip("/"), unquote(parsed.fragment) or None


def load_targets(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def content_pages(repo_root: Path) -> list[Path]:
    pages = []
    for path in sorted(repo_root.rglob("*.html")):
        if path.name == "google743f94c5d2ad6d26.html":
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r'<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', raw, re.I):
            pages.append(path)
    return pages


def audit(repo_root: Path, targets: dict) -> dict:
    site_url = targets.get("site", {}).get("url", DEFAULT_SITE_URL).rstrip("/") + "/"
    html_files = content_pages(repo_root)
    pages: list[dict] = []
    errors: list[dict] = []
    opportunities: list[dict] = []
    titles: list[str] = []
    descriptions: list[str] = []
    for path in html_files:
        rel = path.relative_to(repo_root).as_posix()
        raw = path.read_text(encoding="utf-8", errors="replace")
        parser = parse_page(path)
        title = parser.title.strip()
        description = meta_value(parser, name="description") or ""
        canonical = canonical_value(raw)
        h1 = [t for tag, t in parser.headings if tag == "h1"]
        h2 = [t for tag, t in parser.headings if tag == "h2"]
        types, invalid_jsonld = schema_types(parser)
        images_missing_alt = [x.get("src", "") for x in parser.images if not x.get("alt", "").strip()]
        local_missing: list[str] = []
        local_links = 0
        for link in parser.links:
            ref = internal_reference(link.get("href", ""), rel)
            if not ref:
                continue
            local_links += 1
            target, fragment = ref
            target_path = repo_root / target
            if not target_path.exists():
                local_missing.append(link.get("href", ""))
            elif fragment and target_path.suffix.lower() == ".html":
                target_ids = parse_page(target_path).ids
                if fragment not in target_ids:
                    local_missing.append(link.get("href", ""))
        page = {
            "path": rel, "title": title, "title_length": len(title),
            "description": description, "description_length": len(description),
            "canonical": canonical, "h1": h1, "h2": h2,
            "images": len(parser.images), "images_missing_alt": images_missing_alt,
            "internal_links": local_links, "broken_local_links": local_missing,
            "word_count": len(re.findall(r"\b[\w’'-]+\b", parser.text)),
            "schema_types": types, "invalid_jsonld": invalid_jsonld,
            "has_open_graph": bool(meta_value(parser, prop="og:title") and meta_value(parser, prop="og:description")),
            "has_twitter_card": bool(meta_value(parser, name="twitter:card")),
            "has_contact": bool(re.search(r"(?:mailto:|@|contact|conversation)", parser.text, re.I)),
            "has_company_identity": bool(re.search(r"strativa energy", parser.text, re.I)),
            "visible_question_headings": [t for tag, t in parser.headings if "?" in t],
        }
        pages.append(page)
        titles.append(title)
        descriptions.append(description)

        def issue(code: str, message: str, severity: str = "warning") -> None:
            errors.append({"code": code, "page": rel, "severity": severity, "message": message})

        def opportunity(code: str, message: str) -> None:
            opportunities.append({"code": code, "page": rel, "message": message})

        if not title: issue("missing_title", "Missing title tag", "error")
        elif len(title) < 30 or len(title) > 60: issue("title_length", f"Title length is {len(title)} characters")
        if not description: issue("missing_description", "Missing meta description", "error")
        elif len(description) < 70 or len(description) > 160: issue("description_length", f"Meta description length is {len(description)} characters")
        if len(h1) != 1: issue("h1_structure", f"Expected one H1, found {len(h1)}")
        if not h2: opportunity("missing_h2", "Add clear H2 sections if the page has multiple topics")
        if not canonical: issue("missing_canonical", "Missing canonical URL", "error")
        if not page["has_open_graph"]: opportunity("open_graph", "Add complete Open Graph title and description")
        if not page["has_twitter_card"]: opportunity("twitter_card", "Add Twitter Card metadata")
        if images_missing_alt: issue("missing_alt", f"{len(images_missing_alt)} image(s) are missing alt text")
        if local_missing: issue("broken_local_links", "Broken local links: " + ", ".join(local_missing), "error")
        if invalid_jsonld: issue("invalid_jsonld", "One or more JSON-LD blocks are invalid", "error")
        if page["word_count"] < 250: opportunity("thin_content", f"Visible text is approximately {page['word_count']} words; review whether more useful detail is needed")
        if not page["has_contact"]: opportunity("missing_contact", "Add visible contact information")
        if not page["has_company_identity"]: opportunity("missing_identity", "Clarify company identity in visible content")
        if not types: opportunity("missing_schema", "Review whether appropriate structured data can be added")
        if "Organization" not in types: opportunity("organization_schema", "Review Organization schema")
        if not any(x in types for x in ("ProfessionalService", "LocalBusiness")):
            opportunity("service_business_schema", "Review ProfessionalService or LocalBusiness schema where appropriate")
        if not page["visible_question_headings"]: opportunity("aeo_questions", "Review opportunities for direct, visible answer blocks; do not publish FAQ automatically")
        geo_signals = (
            page["has_company_identity"]
            and bool(re.search(r"Australia|Australian|Melbourne|VIC", parser.text, re.I))
            and bool(re.search(r"solar|battery|BESS|development|approvals|grid", parser.text, re.I))
            and page["has_contact"]
        )
        if not geo_signals:
            opportunity("geo_review", "Review entity, service, location, contact, and evidence clarity for GEO")

    duplicates = {value: count for value, count in Counter(x for x in titles if x).items() if count > 1}
    duplicate_descriptions = {value: count for value, count in Counter(x for x in descriptions if x).items() if count > 1}
    for value, count in duplicates.items():
        errors.append({"code": "duplicate_title", "page": "*", "severity": "warning", "message": f"Duplicate title appears {count} times: {value}"})
    for value, count in duplicate_descriptions.items():
        errors.append({"code": "duplicate_description", "page": "*", "severity": "warning", "message": f"Duplicate description appears {count} times: {value}"})

    robots_path = repo_root / "robots.txt"
    sitemap_path = repo_root / "sitemap.xml"
    robots = robots_path.read_text(encoding="utf-8", errors="replace") if robots_path.exists() else ""
    sitemap = sitemap_path.read_text(encoding="utf-8", errors="replace") if sitemap_path.exists() else ""
    sitemap_urls = re.findall(r"<loc>\s*([^<]+)\s*</loc>", sitemap)
    page_urls = [site_url if p.name == "index.html" else site_url + p.relative_to(repo_root).with_suffix("").as_posix() + ".html" for p in html_files]
    if not robots_path.exists(): errors.append({"code": "missing_robots", "page": "robots.txt", "severity": "error", "message": "robots.txt is missing"})
    elif "Sitemap:" not in robots: opportunities.append({"code": "robots_sitemap", "page": "robots.txt", "message": "Add a Sitemap directive"})
    if not sitemap_path.exists(): errors.append({"code": "missing_sitemap", "page": "sitemap.xml", "severity": "error", "message": "sitemap.xml is missing"})
    for url in page_urls:
        if url not in sitemap_urls:
            errors.append({"code": "page_missing_from_sitemap", "page": "sitemap.xml", "severity": "warning", "message": f"Content page is missing from sitemap: {url}"})
    stale_sitemap = [url for url in sitemap_urls if url not in page_urls]
    if stale_sitemap:
        errors.append({"code": "stale_sitemap_url", "page": "sitemap.xml", "severity": "warning", "message": "Sitemap contains non-published URLs: " + ", ".join(stale_sitemap)})
    return {
        "audit_version": "1.1.0", "site": site_url,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "pages_checked": len(html_files), "pages": pages, "robots": {"exists": robots_path.exists(), "has_sitemap_directive": "Sitemap:" in robots},
        "sitemap": {"exists": sitemap_path.exists(), "urls": sitemap_urls, "pages_missing": [u for u in page_urls if u not in sitemap_urls], "stale_urls": stale_sitemap},
        "errors": errors, "improvement_opportunities": opportunities,
        "aeo_review_queue": [{"question": q, "status": "review_required", "note": "Do not publish automatically; use only approved visible content."} for q in targets.get("aeo_questions", [])],
        "geo_review_queue": targets.get("geo_review_queue", []),
        "recommended_next_steps": ["Review title and meta description lengths before changing copy.", "Keep FAQ answers and FAQPage schema manual and approval-based.", "Add only evidence-backed structured data that matches visible page content.", "Run the optimizer in dry-run mode before reviewing any pull request."],
    }


def markdown_report(result: dict) -> str:
    lines = ["# Strativa Energy SEO AEO GEO Audit", "", f"- Generated: `{result['generated_at']}`", f"- Pages checked: **{result['pages_checked']}**", f"- Errors and warnings: **{len(result['errors'])}**", f"- Improvement opportunities: **{len(result['improvement_opportunities'])}**", "", "## Page Summary", "", "| Page | Title | Description | H1 | H2 | Internal links | Schema | Missing alt | Broken local links |", "|---|---:|---:|---:|---:|---:|---|---:|---:|"]
    for p in result["pages"]:
        lines.append(f"| `{p['path']}` | {p['title_length']} | {p['description_length']} | {len(p['h1'])} | {len(p['h2'])} | {p['internal_links']} | {', '.join(p['schema_types']) or 'None'} | {len(p['images_missing_alt'])} | {len(p['broken_local_links'])} |")
    lines += ["", "## Errors and Warnings", ""]
    lines += [f"- **{x['severity'].upper()}** `{x['code']}` — `{x['page']}`: {x['message']}" for x in result["errors"]] or ["- None found."]
    lines += ["", "## Improvement Opportunities", ""]
    lines += [f"- `{x['code']}` — `{x['page']}`: {x['message']}" for x in result["improvement_opportunities"]] or ["- None found."]
    lines += ["", "## AEO Review Queue", ""]
    lines += [f"- {x['question']} — **{x['status']}**. {x['note']}" for x in result["aeo_review_queue"]] or ["- No questions configured."]
    lines += ["", "## GEO Review Queue", ""]
    lines += [f"- `{x.get('topic', 'review')}` — {x.get('description', '')}" for x in result["geo_review_queue"]] or ["- No items configured."]
    lines += ["", "## Recommended Next Steps", ""] + [f"1. {x}" for x in result["recommended_next_steps"]] + ["", "_This report is informational and does not modify live website content._", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--targets", default="config/seo_targets.json")
    ap.add_argument("--json-out", default="reports/seo-audit-latest.json")
    ap.add_argument("--markdown-out", default="reports/seo-audit-latest.md")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    result = audit(root, load_targets(root / args.targets))
    json_path, md_path = root / args.json_out, root / args.markdown_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    print(f"Audited {result['pages_checked']} page(s); {len(result['errors'])} issue(s); {len(result['improvement_opportunities'])} opportunity(ies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
