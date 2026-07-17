#!/usr/bin/env python3
"""Fetch configured RSS/Atom feeds and build a static GitHub Pages directory."""

from __future__ import annotations

import argparse
import calendar
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
import yaml
from lxml import etree
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ALLOWED_ROOTS = {"rss", "feed", "RDF"}
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"


@dataclass
class Result:
    id: str
    name: str
    output: str
    source_url: str
    status: str
    http_status: int | None = None
    item_count: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    updated_at: str | None = None
    message: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    feeds = raw.get("feeds") or []
    if not isinstance(defaults, dict) or not isinstance(feeds, list):
        raise ValueError("config must contain a defaults mapping and a feeds list")
    return defaults, feeds


def validate_feed_config(feed: dict[str, Any]) -> None:
    for key in ("id", "name", "url", "output"):
        if not feed.get(key):
            raise ValueError(f"feed is missing required field: {key}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(feed["id"])):
        raise ValueError(f"invalid feed id: {feed['id']}")
    parsed = urlparse(str(feed["url"]))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid feed URL: {feed['url']}")
    output = PurePosixPath(str(feed["output"]))
    if output.is_absolute() or ".." in output.parts or output.suffix.lower() not in {".xml", ".rss", ".atom"}:
        raise ValueError(f"unsafe output path: {feed['output']}")
    if str(feed.get("mode", "passthrough")) not in {"passthrough", "normalize"}:
        raise ValueError(f"unsupported mode for {feed['id']}: {feed.get('mode')}")


def make_session(feed: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    retries = int(feed.get("retries", 3))
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=float(feed.get("retry_backoff", 1.5)),
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": str(feed.get("user_agent", "RSS-Relay/1.0")),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
    })
    for key, value in (feed.get("headers") or {}).items():
        session.headers[str(key)] = str(value)
    for header, env_name in (feed.get("headers_from_env") or {}).items():
        value = os.environ.get(str(env_name))
        if not value:
            raise ValueError(f"required environment variable is missing: {env_name}")
        session.headers[str(header)] = value
    return session


def fetch(feed: dict[str, Any]) -> tuple[bytes, int, str]:
    timeout = float(feed.get("timeout", 30))
    max_bytes = int(feed.get("max_bytes", 20 * 1024 * 1024))
    session = make_session(feed)
    warmup_url = feed.get("warmup_url")
    if warmup_url:
        warmup = session.get(str(warmup_url), timeout=timeout, allow_redirects=True)
        if bool(feed.get("warmup_required", False)):
            warmup.raise_for_status()
        delay = float(feed.get("warmup_delay", 0.5))
        if delay > 0:
            time.sleep(delay)

    with session.get(str(feed["url"]), timeout=timeout, allow_redirects=True, stream=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"response exceeds max_bytes={max_bytes}")
            chunks.append(chunk)
        body = b"".join(chunks)
        if not body.strip():
            raise ValueError("source returned an empty response")
        return body, response.status_code, content_type


def parse_xml(body: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=False)
    root = etree.fromstring(body, parser=parser)
    local_name = etree.QName(root.tag).localname
    if local_name not in ALLOWED_ROOTS:
        raise ValueError(f"XML root <{local_name}> is not RSS, Atom, or RDF")
    return root


def looks_like_html(body: bytes, content_type: str) -> bool:
    prefix = body[:1024].lstrip().lower()
    return "text/html" in content_type or prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")


def text_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, dict):
        return str(value.get("value") or value.get("href") or default)
    return str(value)


def parsed_date(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return email.utils.formatdate(calendar.timegm(value), usegmt=True)
    return None


def add_text(parent: etree._Element, tag: str, value: Any) -> etree._Element | None:
    text = text_value(value).strip()
    if not text:
        return None
    node = etree.SubElement(parent, tag)
    node.text = text
    return node


def normalize_to_rss(body: bytes, feed: dict[str, Any]) -> tuple[bytes, int]:
    parsed = feedparser.parse(body, resolve_relative_uris=True, sanitize_html=True)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"feedparser could not parse the feed: {parsed.bozo_exception}")
    meta = parsed.feed
    root = etree.Element("rss", version="2.0", nsmap={"content": CONTENT_NS, "atom": ATOM_NS})
    channel = etree.SubElement(root, "channel")
    title = feed.get("title_override") or meta.get("title") or feed["name"]
    link = feed.get("link_override") or meta.get("link") or feed["url"]
    description = meta.get("subtitle") or meta.get("description") or title
    add_text(channel, "title", title)
    add_text(channel, "link", link)
    add_text(channel, "description", description)
    add_text(channel, "language", meta.get("language"))
    add_text(channel, "generator", "GitHub Actions RSS Relay")
    atom_link = etree.SubElement(channel, f"{{{ATOM_NS}}}link")
    atom_link.set("href", str(feed["url"]))
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    entries = parsed.entries[: int(feed.get("max_items", 100))]
    for entry in entries:
        item = etree.SubElement(channel, "item")
        add_text(item, "title", entry.get("title") or "Untitled")
        add_text(item, "link", entry.get("link"))
        description_value = entry.get("summary") or entry.get("description")
        add_text(item, "description", description_value)
        content = entry.get("content") or []
        if content:
            add_text(item, f"{{{CONTENT_NS}}}encoded", content[0].get("value"))
        guid_value = entry.get("id") or entry.get("guid") or entry.get("link")
        guid = add_text(item, "guid", guid_value)
        if guid is not None:
            guid.set("isPermaLink", "true" if guid_value == entry.get("link") else "false")
        add_text(item, "pubDate", parsed_date(entry))
        author = entry.get("author")
        if not author and entry.get("authors"):
            author = ", ".join(text_value(x.get("name")) for x in entry.authors if x.get("name"))
        add_text(item, "author", author)
        for tag in entry.get("tags") or []:
            add_text(item, "category", tag.get("term"))
        for enclosure in entry.get("enclosures") or []:
            href = enclosure.get("href") or enclosure.get("url")
            if not href:
                continue
            node = etree.SubElement(item, "enclosure")
            node.set("url", str(href))
            node.set("type", str(enclosure.get("type") or "application/octet-stream"))
            if enclosure.get("length"):
                node.set("length", str(enclosure["length"]))

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True), len(entries)


def count_items(root: etree._Element) -> int:
    local = etree.QName(root.tag).localname
    if local == "feed":
        return len(root.xpath("./*[local-name()='entry']"))
    return len(root.xpath(".//*[local-name()='item']"))


def process_feed(feed: dict[str, Any], public_dir: Path) -> Result:
    output = public_dir / PurePosixPath(str(feed["output"]))
    result = Result(
        id=str(feed["id"]), name=str(feed["name"]), output=str(feed["output"]),
        source_url=str(feed["url"]), status="failed", updated_at=utc_now(),
    )
    try:
        validate_feed_config(feed)
        body, http_status, content_type = fetch(feed)
        result.http_status = http_status
        if looks_like_html(body, content_type):
            raise ValueError("source returned HTML instead of a feed (often a WAF/challenge page)")
        root = parse_xml(body)
        if feed.get("mode", "passthrough") == "normalize":
            body, item_count = normalize_to_rss(body, feed)
            root = parse_xml(body)
        else:
            item_count = count_items(root)
        if bool(feed.get("require_items", True)) and item_count == 0:
            raise ValueError("feed parsed successfully but contains zero items")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(output)
        result.status = "updated"
        result.item_count = item_count
        result.bytes = len(body)
        result.sha256 = hashlib.sha256(body).hexdigest()
        result.message = "ok"
    except Exception as exc:  # one bad source must not block all other feeds
        policy = str(feed.get("failure_policy", "keep_old"))
        if policy == "keep_old" and output.exists():
            old = output.read_bytes()
            result.status = "stale"
            result.bytes = len(old)
            result.sha256 = hashlib.sha256(old).hexdigest()
            result.message = f"update failed; kept previous version: {exc}"
        else:
            result.message = str(exc)
    return result


def build_index(results: list[Result], public_dir: Path, generated_at: str) -> None:
    rows = []
    for result in results:
        state = {"updated": "正常", "stale": "旧版", "failed": "失败"}.get(result.status, result.status)
        link = html.escape(result.output, quote=True)
        rows.append(
            "<tr>"
            f"<td>{html.escape(result.name)}</td>"
            f"<td><a href=\"{link}\">{link}</a></td>"
            f"<td>{state}</td><td>{result.item_count if result.item_count is not None else '-'}</td>"
            f"<td>{html.escape(result.message)}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RSS Relay</title><style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#222}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.6rem;text-align:left;vertical-align:top}}
th{{background:#f5f5f5}}code{{background:#f5f5f5;padding:.1rem .3rem}}small{{color:#666}}
</style></head><body><h1>RSS Relay</h1>
<p>生成时间：<code>{html.escape(generated_at)}</code></p>
<table><thead><tr><th>订阅源</th><th>Glean 订阅地址</th><th>状态</th><th>条目数</th><th>说明</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p><small>状态“旧版”表示本次拉取失败，仍提供上一次成功生成的内容。</small></p>
</body></html>"""
    (public_dir / "index.html").write_text(document, encoding="utf-8")
    (public_dir / ".nojekyll").touch()


def write_summary(results: list[Result]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = ["## RSS 更新结果", "", "| ID | 状态 | 条目 | 说明 |", "|---|---:|---:|---|"]
    for result in results:
        message = result.message.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{result.id}` | {result.status} | {result.item_count or '-'} | {message} |")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/feeds.yml")
    parser.add_argument("--output", default="public")
    args = parser.parse_args()
    config_path = Path(args.config)
    public_dir = Path(args.output)
    public_dir.mkdir(parents=True, exist_ok=True)

    defaults, configured_feeds = load_config(config_path)
    results: list[Result] = []
    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    for configured in configured_feeds:
        if not isinstance(configured, dict) or not configured.get("enabled", True):
            continue
        feed = {**defaults, **configured}
        feed["headers"] = {**(defaults.get("headers") or {}), **(configured.get("headers") or {})}
        feed["headers_from_env"] = {
            **(defaults.get("headers_from_env") or {}), **(configured.get("headers_from_env") or {})
        }
        validate_feed_config(feed)
        if feed["id"] in seen_ids or feed["output"] in seen_outputs:
            raise ValueError(f"duplicate feed id or output: {feed['id']} / {feed['output']}")
        seen_ids.add(str(feed["id"]))
        seen_outputs.add(str(feed["output"]))
        result = process_feed(feed, public_dir)
        results.append(result)
        print(f"[{result.status.upper()}] {result.id}: {result.message}")

    generated_at = utc_now()
    build_index(results, public_dir, generated_at)
    status = {"generated_at": generated_at, "feeds": [asdict(result) for result in results]}
    (public_dir / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_summary(results)
    failures = [result for result in results if result.status != "updated"]
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(2)
