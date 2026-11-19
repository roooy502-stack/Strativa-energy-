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
        self.link_tags: list[dict[str, str]] = []
        self.script_srcs: list[str] = []
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
        if tag == "link":
            self.link_tags.append(attrs)
        if tag == "script" and attrs.get("src"):
            self.script_srcs.append(attrs["src"])
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
            flat = []
            for item in values:
                if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                    flat.extend(item["@graph"])
                else:
                    flat.append(item)
            for item in flat:
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


SKIP_DIRS = {".git", "partials", "reports", "node_modules", "google-apps-script", "scripts", "config", "assets"}
NOINDEX_RE = re.compile(r'<meta\b[^>]*name=["\']robots["\'][^>]*content=["\'][^"\']*noindex', re.I)


def all_pages(repo_root: Path) -> list[Path]:
    """Every real HTML page (excluding verification files, partials and tooling folders)."""
    pages = []
    for path in sorted(repo_root.rglob("*.html")):
        rel = path.relative_to(repo_root)
        if set(rel.parts[:-1]) & SKIP_DIRS:
            continue
        if rel.parent == Path(".") and path.name.startswith("google"):
            continue
        pages.append(path)
    return pages


def is_noindex(path: Path) -> bool:
    return bool(NOINDEX_RE.search(path.read_text(encoding="utf-8", errors="replace")))


def content_pages(repo_root: Path) -> list[Path]:
    return [p for p in all_pages(repo_root) if not is_noindex(p)]


def expected_url(rel: str, site_url: str) -> str:
    """Public URL a page file is served at (directory-style URLs with trailing slash)."""
    path = Path(rel)
    if path.name == "index.html":
        parent = path.parent.as_posix()
        return site_url if parent == "." else f"{site_url}{parent}/"
    return site_url + rel


def local_target(ref: str, page_rel: str) -> str | None:
    """Resolve a local src/href to a repo-relative file path (no fragment), or None for external."""
    if not ref or ref.startswith(("mailto:", "tel:", "data:", "javascript:", "#", "//")):
        return None
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc:
        return None
    raw = parsed.path
    if not raw:
        return None
    base = Path(page_rel).parent
    target = raw.lstrip("/") if raw.startswith("/") else (base / raw).as_posix()
    if target.endswith("/") or target == "":
        target += "index.html"
    return unquote(target)


def jsonld_problems(raw: str) -> list[str]:
    problems: list[str] = []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"invalid JSON ({exc.msg})"]
    nodes = value.get("@graph", [value]) if isinstance(value, dict) else value
    if isinstance(value, dict) and "@context" not in value:
        problems.append("missing @context")
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if not kind:
            problems.append("node without @type")
            continue
        if "BreadcrumbList" in kinds:
            items = node.get("itemListElement") or []
            if not items:
                problems.append("BreadcrumbList without items")
            for idx, item in enumerate(items, 1):
                if item.get("position") != idx or not item.get("name") or not item.get("item"):
                    problems.append(f"BreadcrumbList item {idx} incomplete")
        if "Article" in kinds:
            for key in ("headline", "datePublished", "author", "publisher"):
                if not node.get(key):
                    problems.append(f"Article missing {key}")
        if "Organization" in kinds and not (node.get("name") and node.get("url")):
            problems.append("Organization missing name or url")
    return problems


def audit(repo_root: Path, targets: dict) -> dict:
    site_url = targets.get("site", {}).get("url", DEFAULT_SITE_URL).rstrip("/") + "/"
    host = site_url.rstrip("/")
    files = all_pages(repo_root)
    indexable = [p for p in files if not is_noindex(p)]
    pages: list[dict] = []
    errors: list[dict] = []
    opportunities: list[dict] = []
    titles: dict[str, list[str]] = {}
    descriptions: dict[str, list[str]] = {}
    h1s: dict[str, list[str]] = {}
    inbound: dict[str, set[str]] = {}
    parsed_cache: dict[str, PageParser] = {}

    def issue(code: str, page: str, message: str, severity: str = "warning") -> None:
        errors.append({"code": code, "page": page, "severity": severity, "message": message})

    def opportunity(code: str, page: str, message: str) -> None:
        opportunities.append({"code": code, "page": page, "message": message})

    for path in files:
        parsed_cache[path.relative_to(repo_root).as_posix()] = parse_page(path)

    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        raw = path.read_text(encoding="utf-8", errors="replace")
        parser = parsed_cache[rel]
        noindex = is_noindex(path)
        title = parser.title.strip()
        description = meta_value(parser, name="description") or ""
        canonical = canonical_value(raw)
        h1 = [t for tag, t in parser.headings if tag == "h1"]
        h2 = [t for tag, t in parser.headings if tag == "h2"]
        types, invalid_jsonld = schema_types(parser)
        images_missing_alt = [x.get("src", "") for x in parser.images if "alt" not in x]
        empty_alt_nonlocal = [x.get("src", "") for x in parser.images if x.get("alt") == "" and x.get("role") != "presentation" and x.get("aria-hidden") != "true"]
        local_missing: list[str] = []
        local_links = 0
        for link in parser.links:
            href = link.get("href", "")
            ref = internal_reference(href, rel)
            if not ref:
                if href.startswith("http") and link.get("target") == "_blank" and "noopener" not in link.get("rel", ""):
                    issue("external_link_rel", rel, f"target=_blank link without rel=noopener: {href}")
                continue
            local_links += 1
            target, fragment = ref
            target_path = repo_root / target
            if not target_path.exists():
                local_missing.append(href)
                continue
            target_rel = target_path.relative_to(repo_root).as_posix()
            if target_rel != rel:
                inbound.setdefault(target_rel, set()).add(rel)
            if fragment and target_path.suffix.lower() == ".html":
                tparser = parsed_cache.get(target_rel) or parse_page(target_path)
                if fragment not in tparser.ids:
                    local_missing.append(href)
            clean = urlparse(href).path
            if clean and not clean.endswith("/") and "." not in Path(clean).name and not clean.startswith("mailto"):
                issue("link_trailing_slash", rel, f"Internal link without trailing slash (causes a redirect on most hosts): {href}")
        # local assets: images, stylesheets, scripts, icons, preload
        missing_assets: list[str] = []
        refs = [x.get("src", "") for x in parser.images] + parser.script_srcs + [x.get("href", "") for x in parser.link_tags if x.get("rel", "").lower() not in {"canonical"}]
        for ref in refs:
            target = local_target(ref, rel)
            if target and not (repo_root / target).exists():
                missing_assets.append(ref)
        page = {
            "path": rel, "url": expected_url(rel, site_url), "indexable": not noindex,
            "title": title, "title_length": len(title),
            "description": description, "description_length": len(description),
            "canonical": canonical, "h1": h1, "h2": h2,
            "images": len(parser.images), "images_missing_alt": images_missing_alt,
            "internal_links": local_links, "broken_local_links": local_missing, "missing_assets": missing_assets,
            "word_count": len(re.findall(r"\b[\w’'-]+\b", parser.text)),
            "schema_types": types, "invalid_jsonld": invalid_jsonld,
            "has_open_graph": bool(meta_value(parser, prop="og:title") and meta_value(parser, prop="og:description")),
            "has_twitter_card": bool(meta_value(parser, name="twitter:card")),
            "has_contact": bool(re.search(r"(?:mailto:|@|contact|conversation)", parser.text, re.I)),
            "has_company_identity": bool(re.search(r"strativa energy", parser.text, re.I)),
            "visible_question_headings": [t for tag, t in parser.headings if "?" in t],
        }
        pages.append(page)
        if noindex:
            continue
        titles.setdefault(title, []).append(rel)
        descriptions.setdefault(description, []).append(rel)
        if h1:
            h1s.setdefault(h1[0], []).append(rel)

        if not title: issue("missing_title", rel, "Missing title tag", "error")
        elif len(title) < 25 or len(title) > 65: issue("title_length", rel, f"Title length is {len(title)} characters")
        if not description: issue("missing_description", rel, "Missing meta description", "error")
        elif len(description) < 70 or len(description) > 165: issue("description_length", rel, f"Meta description length is {len(description)} characters")
        if len(h1) != 1: issue("h1_structure", rel, f"Expected one H1, found {len(h1)}")
        levels = [int(tag[1]) for tag, _ in parser.headings]
        for prev, cur in zip(levels, levels[1:]):
            if cur > prev + 1:
                issue("heading_skip", rel, f"Heading level jumps from h{prev} to h{cur}")
                break
        if not h2: opportunity("missing_h2", rel, "Add clear H2 sections if the page has multiple topics")
        if not canonical:
            issue("missing_canonical", rel, "Missing canonical URL", "error")
        elif canonical != page["url"]:
            issue("canonical_mismatch", rel, f"Canonical {canonical} differs from the page's own URL {page['url']}", "error")
        if not (parser.meta and any(m.get("charset") for m in parser.meta)): issue("missing_charset", rel, "Missing meta charset")
        if not any(m.get("name") == "viewport" for m in parser.meta): issue("missing_viewport", rel, "Missing viewport meta tag", "error")
        if not re.search(r"<html[^>]*\blang=[\"']en-AU", raw, re.I): issue("html_lang", rel, "html lang is not en-AU")
        if not page["has_open_graph"]: issue("open_graph", rel, "Incomplete Open Graph title/description")
        ogimg = meta_value(parser, prop="og:image") or ""
        if not ogimg.startswith(host + "/"): issue("og_image", rel, "og:image missing or not an absolute production URL")
        else:
            og_local = ogimg[len(host) + 1:]
            if not (repo_root / og_local).exists(): issue("og_image_missing", rel, f"og:image file not found: {og_local}", "error")
        if (meta_value(parser, prop="og:url") or "") != (canonical or ""): issue("og_url_mismatch", rel, "og:url differs from canonical")
        if not page["has_twitter_card"]: opportunity("twitter_card", rel, "Add Twitter Card metadata")
        if images_missing_alt: issue("missing_alt", rel, f"{len(images_missing_alt)} image(s) are missing an alt attribute")
        if local_missing: issue("broken_local_links", rel, "Broken local links: " + ", ".join(local_missing), "error")
        if missing_assets: issue("missing_assets", rel, "Referenced local files not found: " + ", ".join(missing_assets), "error")
        if invalid_jsonld: issue("invalid_jsonld", rel, "One or more JSON-LD blocks are invalid", "error")
        for raw_ld in parser.jsonld:
            for prob in jsonld_problems(raw_ld):
                issue("jsonld_property", rel, prob, "error")
        nested = Path(rel).parent != Path(".")
        if nested and "BreadcrumbList" not in " ".join(types) and rel != "404.html":
            issue("missing_breadcrumb_schema", rel, "Nested page has no BreadcrumbList structured data")
        if nested and not any('class="breadcrumb"' in raw for _ in [0]):
            issue("missing_breadcrumb", rel, "Nested page has no visible breadcrumb")
        if page["word_count"] < 250 and rel not in {"insights/index.html"}:
            opportunity("thin_content", rel, f"Visible text is approximately {page['word_count']} words; review whether more useful detail is needed")
        if not page["has_company_identity"]: opportunity("missing_identity", rel, "Clarify company identity in visible content")
        if not types: opportunity("missing_schema", rel, "Review whether appropriate structured data can be added")
        if not page["visible_question_headings"] and rel in {"index.html", "about/index.html"}:
            opportunity("aeo_questions", rel, "Review opportunities for direct, visible answer blocks; do not publish FAQ automatically")

    for label, bucket in (("title", titles), ("description", descriptions), ("h1", h1s)):
        for value, owners in bucket.items():
            if value and len(owners) > 1:
                issue(f"duplicate_{label}", "*", f"Duplicate {label} on {', '.join(owners)}: {value}")

    # orphan pages: indexable pages with no inbound internal link
    for path in indexable:
        rel = path.relative_to(repo_root).as_posix()
        if rel != "index.html" and not inbound.get(rel):
            issue("orphan_page", rel, "No other page links to this page", "error")

    robots_path = repo_root / "robots.txt"
    sitemap_path = repo_root / "sitemap.xml"
    robots = robots_path.read_text(encoding="utf-8", errors="replace") if robots_path.exists() else ""
    sitemap = sitemap_path.read_text(encoding="utf-8", errors="replace") if sitemap_path.exists() else ""
    sitemap_urls = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", sitemap)
    page_urls = [expected_url(p.relative_to(repo_root).as_posix(), site_url) for p in indexable]
    noindex_urls = [expected_url(p.relative_to(repo_root).as_posix(), site_url) for p in files if is_noindex(p)]
    if not robots_path.exists():
        issue("missing_robots", "robots.txt", "robots.txt is missing", "error")
    else:
        if f"Sitemap: {site_url}sitemap.xml" not in robots: issue("robots_sitemap", "robots.txt", f"robots.txt should declare 'Sitemap: {site_url}sitemap.xml'")
        if re.search(r"^\s*Disallow:\s*/\s*$", robots, re.M): issue("robots_blocks_all", "robots.txt", "robots.txt blocks the whole site", "error")
        if re.search(r"^\s*Disallow:.*(\.css|\.js|/assets)", robots, re.M | re.I): issue("robots_blocks_assets", "robots.txt", "robots.txt blocks CSS, JavaScript or assets", "error")
    if not sitemap_path.exists():
        issue("missing_sitemap", "sitemap.xml", "sitemap.xml is missing", "error")
    else:
        try:
            from xml.dom import minidom
            minidom.parseString(sitemap.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            issue("sitemap_xml_invalid", "sitemap.xml", f"sitemap.xml is not valid XML: {exc}", "error")
        if 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' not in sitemap: issue("sitemap_namespace", "sitemap.xml", "Missing sitemap namespace", "error")
    for url in page_urls:
        if url not in sitemap_urls:
            issue("page_missing_from_sitemap", "sitemap.xml", f"Indexable page is missing from sitemap: {url}")
    stale = [u for u in sitemap_urls if u not in page_urls]
    if stale:
        issue("stale_sitemap_url", "sitemap.xml", "Sitemap contains URLs that are not indexable canonical pages: " + ", ".join(stale))
    for u in sitemap_urls:
        if not u.startswith("https://"): issue("sitemap_not_https", "sitemap.xml", f"Non-HTTPS URL in sitemap: {u}", "error")
        if u in noindex_urls: issue("sitemap_noindex", "sitemap.xml", f"noindex page in sitemap: {u}", "error")
    if len(sitemap_urls) != len(set(sitemap_urls)): issue("sitemap_duplicates", "sitemap.xml", "Duplicate URLs in sitemap", "error")
    if re.search(r"<(changefreq|priority)>", sitemap): opportunity("sitemap_hints", "sitemap.xml", "changefreq and priority are ignored by Google; consider removing them")

    return {
        "audit_version": "2.0.0", "site": site_url,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "pages_checked": len(files), "indexable_pages": len(indexable),
        "pages": pages, "robots": {"exists": robots_path.exists(), "has_sitemap_directive": "Sitemap:" in robots},
        "sitemap": {"exists": sitemap_path.exists(), "urls": sitemap_urls, "pages_missing": [u for u in page_urls if u not in sitemap_urls], "stale_urls": stale},
        "errors": errors, "improvement_opportunities": opportunities,
        "aeo_review_queue": [{"question": q, "status": "review_required", "note": "Do not publish automatically; use only approved visible content."} for q in targets.get("aeo_questions", [])],
        "geo_review_queue": targets.get("geo_review_queue", []),
        "recommended_next_steps": ["Review title and meta description lengths before changing copy.", "Keep FAQ answers and FAQPage schema manual and approval-based.", "Add only evidence-backed structured data that matches visible page content.", "Run the optimizer in dry-run mode before reviewing any pull request."],
    }


def markdown_report(result: dict) -> str:
    lines = ["# Strativa Energy SEO AEO GEO Audit", "", f"- Generated: `{result['generated_at']}`", f"- Pages checked: **{result['pages_checked']}** ({result['indexable_pages']} indexable)", f"- Errors and warnings: **{len(result['errors'])}**", f"- Improvement opportunities: **{len(result['improvement_opportunities'])}**", "", "## Page Summary", "", "| Page | Indexable | Title | Description | H1 | H2 | Internal links | Schema | Missing alt | Broken links |", "|---|---|---:|---:|---:|---:|---:|---|---:|---:|"]
    for p in result["pages"]:
        lines.append(f"| `{p['path']}` | {'yes' if p['indexable'] else 'no'} | {p['title_length']} | {p['description_length']} | {len(p['h1'])} | {len(p['h2'])} | {p['internal_links']} | {', '.join(p['schema_types']) or 'None'} | {len(p['images_missing_alt'])} | {len(p['broken_local_links'])} |")
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
    ap.add_argument("--strict", action="store_true", help="exit with status 1 if any error-severity issue is found")
    args = ap.parse_args()
    root = Path(args.repo_root).resolve()
    result = audit(root, load_targets(root / args.targets))
    json_path, md_path = root / args.json_out, root / args.markdown_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")
    print(f"Audited {result['pages_checked']} page(s); {len(result['errors'])} issue(s); {len(result['improvement_opportunities'])} opportunity(ies).")
    if args.strict and any(e["severity"] == "error" for e in result["errors"]):
        print("Strict mode: error-severity issues found.", file=sys.stderr)
        for e in result["errors"]:
            if e["severity"] == "error":
                print(f"  {e['code']} {e['page']}: {e['message']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
