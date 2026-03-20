from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from lxml import html

from onefetch.adapters.base import BaseAdapter, node_to_text
from onefetch.adapters.generic_html import GenericHtmlAdapter
from onefetch.models import FeedEntry
from onefetch.router import normalize_url


class GeekbangAdapter(BaseAdapter):
    id = "geekbang"
    priority = 320

    def supports(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        path = urlparse(url).path or ""
        return host == "b.geekbang.org" and path.startswith("/member/course/")

    async def crawl(self, url: str) -> FeedEntry:
        fallback = GenericHtmlAdapter()
        feed = await fallback.crawl(url)
        try:
            tree = html.fromstring(feed.raw_body or "")
            path = urlparse(url).path or ""

            detail = self._extract_detail_content(tree)
            intro = self._extract_intro_content(tree) if not detail else None
            chosen = detail or intro
            if chosen:
                if chosen.get("title"):
                    feed.title = str(chosen["title"]).strip()
                if chosen.get("author"):
                    feed.author = str(chosen["author"]).strip()
                if chosen.get("published_at"):
                    feed.published_at = chosen["published_at"]
                body = self._cleanup_body(str(chosen.get("body") or ""))
                if body:
                    feed.body = body[:60000]
                images = list(chosen.get("images") or [])
                if images:
                    feed.images = images
                feed.metadata = {
                    **(feed.metadata or {}),
                    "content_kind": "detail" if detail else "intro",
                    "path": path,
                }
            feed.canonical_url = normalize_url(feed.canonical_url)
            feed.crawler_id = self.id
            return feed
        except Exception:
            # 解析失败时回退 generic_html 结果
            feed.crawler_id = self.id
            return feed

    @staticmethod
    def _extract_detail_content(tree) -> dict | None:
        wrappers = tree.xpath("//*[contains(@class,'ArticleContent_audio-course-wrapper')]")
        if not wrappers:
            return None
        wrapper = wrappers[0]
        pm_nodes = wrapper.xpath(".//*[contains(@class,'ProseMirror')]")
        if not pm_nodes:
            return None
        body, images = GeekbangAdapter._extract_rich_body(pm_nodes[0])
        title = GeekbangAdapter._first_text(wrapper, ".//*[contains(@class,'ArticleContent_title')][1]")
        author = GeekbangAdapter._first_text(wrapper, ".//*[contains(@class,'ArticleContent_desc')][1]")
        published_text = GeekbangAdapter._first_text(wrapper, ".//*[contains(@class,'ArticleContent_first-publish')][1]")
        published_at = GeekbangAdapter._parse_date(published_text)
        return {
            "title": title,
            "author": author,
            "published_at": published_at,
            "body": body,
            "images": images,
        }

    @staticmethod
    def _extract_intro_content(tree) -> dict | None:
        wrappers = tree.xpath("//*[contains(@class,'IntroPC_intro-wrapper')]")
        if not wrappers:
            return None
        wrapper = wrappers[0]
        blocks: list[str] = []
        images: list[str] = []
        for node in wrapper.xpath(".//*[contains(@class,'article-typo')]"):
            text, imgs = node_to_text(node, image_placeholders=True)
            cleaned = GeekbangAdapter._cleanup_body(text)
            if cleaned:
                blocks.append(cleaned)
            if imgs:
                images.extend(imgs)
        if not blocks:
            return None
        body = GeekbangAdapter._renumber_img_placeholders("\n\n".join(blocks))
        title = GeekbangAdapter._first_text(
            tree,
            "//*[contains(@class,'ColumnInfoPC_title')] | //*[contains(@class,'ColumnInfoPC_column-title')]",
        )
        author = GeekbangAdapter._first_text(
            tree,
            "//*[contains(@class,'ColumnInfoPC_author')] | //*[contains(@class,'ColumnInfoPC_teacher')]",
        )
        return {
            "title": title,
            "author": author,
            "published_at": None,
            "body": body,
            "images": images,
        }

    @staticmethod
    def _extract_rich_body(node) -> tuple[str, list[str]]:
        blocks: list[str] = []
        images: list[str] = []

        for child in node.xpath("./*"):
            # Skip script/style fragments that may appear in rendered DOM.
            if child.tag in {"script", "style"}:
                continue

            img_nodes = child.xpath(".//img")
            if img_nodes:
                marker_indices: list[int] = []
                for img in img_nodes:
                    src = (img.get("data-src") or img.get("src") or "").strip()
                    if src.startswith("//"):
                        src = "https:" + src
                    if not src or not src.startswith("http"):
                        continue
                    if "svg+xml" in src or "1px" in src:
                        continue
                    images.append(src)
                    idx = len(images)
                    marker_indices.append(idx)
                    blocks.append(f"[IMG:{idx}]")

                caption = GeekbangAdapter._text_without_images(child)
                if caption and marker_indices:
                    for idx in marker_indices:
                        blocks.append(f"[IMG_CAPTION:{idx}] {caption}")
                continue

            text = GeekbangAdapter._clean_text(child.text_content())
            if text:
                blocks.append(text)

        body = "\n\n".join(block for block in blocks if block).strip()
        return body, images

    @staticmethod
    def _text_without_images(node) -> str:
        clone = deepcopy(node)
        for img in clone.xpath(".//img"):
            parent = img.getparent()
            if parent is not None:
                parent.remove(img)
        return GeekbangAdapter._clean_text(clone.text_content())

    @staticmethod
    def _first_text(node, xpath_expr: str) -> str:
        for match in node.xpath(xpath_expr):
            value = GeekbangAdapter._clean_text(match.text_content() if hasattr(match, "text_content") else str(match))
            if value:
                return value
        return ""

    @staticmethod
    def _parse_date(value: str):
        text = (value or "").strip()
        if not text:
            return None
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if not m:
            return None
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d, tzinfo=GeekbangAdapter._CST_TZ)
        except Exception:
            return None

    @staticmethod
    def _clean_text(value: str) -> str:
        text = (value or "").replace("\u00a0", " ").replace("\u200b", "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _cleanup_body(value: str) -> str:
        text = GeekbangAdapter._clean_text(value)
        if not text:
            return text
        noise_patterns = [
            r"We'?re sorry but member\.b\.geekbang\.com doesn't work properly without JavaScript enabled\.?",
            r"Please enable it to continue\.?",
            r"^\(function\(win,\s*export_obj\)",
            r"^win\['LogAnalyticsObject'\]",
            r"^_collect\.q",
            r"^\}\)\(window,\s*'collectEvent'\);?$",
            r"^$",
            r"^$",
            r"^$",
            r"^$",
            r"^问好$",
        ]
        cleaned_lines: list[str] = []
        for line in text.splitlines():
            item = line.strip()
            if not item:
                continue
            if any(re.search(pattern, item) for pattern in noise_patterns):
                continue
            if re.fullmatch(r"[-]+", item):
                continue
            cleaned_lines.append(item)
        text = "\n".join(cleaned_lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def _renumber_img_placeholders(text: str) -> str:
        seq = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal seq
            seq += 1
            return f"[IMG:{seq}]"

        return re.sub(r"\[IMG:\d+\]", _replace, text or "")
    _CST_TZ = timezone(timedelta(hours=8))
