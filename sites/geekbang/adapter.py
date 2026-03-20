from __future__ import annotations

import html as std_html
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from lxml import html

from onefetch.adapters.base import BaseAdapter
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
                images = self._normalize_image_entries(list(chosen.get("images") or []))
                # Always override fallback images once specialized extraction succeeds.
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
        images: list[dict] = []
        for node in wrapper.xpath(".//*[contains(@class,'article-typo')]"):
            text, imgs = GeekbangAdapter._extract_rich_body(node)
            cleaned = GeekbangAdapter._cleanup_body(text)
            if cleaned:
                blocks.append(cleaned)
            if imgs:
                images.extend(imgs)
        if not blocks:
            return None
        body = GeekbangAdapter._renumber_img_placeholders("\n".join(blocks))
        body, images = GeekbangAdapter._filter_images_and_markers(body, images)
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
    def _extract_rich_body(node) -> tuple[str, list[dict]]:
        blocks: list[str] = []
        images: list[dict] = []
        heading_base = GeekbangAdapter._heading_base_level(node)

        for child in node.xpath("./*"):
            # Skip script/style fragments that may appear in rendered DOM.
            if child.tag in {"script", "style"}:
                continue
            heading_block = GeekbangAdapter._extract_heading_block(child, heading_base=heading_base)
            if heading_block:
                blocks.append(heading_block)
                continue
            if GeekbangAdapter._is_code_block_node(child):
                code_block = GeekbangAdapter._extract_code_block(child)
                if code_block:
                    blocks.append(code_block)
                continue
            if GeekbangAdapter._is_list_node(child):
                list_block = GeekbangAdapter._extract_list_block(child)
                if list_block:
                    blocks.append(list_block)
                continue
            if GeekbangAdapter._is_table_node(child):
                table_block = GeekbangAdapter._extract_table_block(child)
                if table_block:
                    blocks.append(table_block)
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
                    if GeekbangAdapter._is_decorative_image(img, src):
                        continue
                    alt = GeekbangAdapter._clean_text(str(img.get("alt") or ""))
                    href = GeekbangAdapter._image_href(img)
                    images.append({"src": src, "alt": alt, "href": href})
                    idx = len(images)
                    marker_indices.append(idx)
                    blocks.append(f"[IMG:{idx}]")

                caption = GeekbangAdapter._text_without_images(child)
                if caption and marker_indices:
                    for idx in marker_indices:
                        blocks.append(f"[IMG_CAPTION:{idx}] {caption}")
                continue

            text = GeekbangAdapter._text_with_links(child)
            if text:
                code_block = GeekbangAdapter._render_compact_code_from_text(text)
                if code_block:
                    blocks.append(code_block)
                else:
                    blocks.append(text)

        body = "\n".join(block for block in blocks if block).strip()
        body, images = GeekbangAdapter._filter_images_and_markers(body, images)
        return body, images

    @staticmethod
    def _heading_base_level(root_node) -> int:
        levels: list[int] = []
        for child in root_node.xpath("./*"):
            tag = str(getattr(child, "tag", "") or "").lower()
            if tag.startswith("h") and tag[1:].isdigit():
                levels.append(int(tag[1:]))
        if not levels:
            return 0
        return min(levels)

    @staticmethod
    def _extract_heading_block(node, *, heading_base: int) -> str:
        tag = str(getattr(node, "tag", "") or "").lower()
        if tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return ""
        try:
            source_level = int(tag[1])
        except Exception:
            source_level = 1
        # Note template uses "# title" + "## 正文".
        # Normalize article headings dynamically: shallowest heading becomes ###.
        base = heading_base if heading_base > 0 else 1
        level = max(3, min(source_level - base + 3, 6))
        text = GeekbangAdapter._text_with_links(node)
        if not text:
            return ""
        return f"{'#' * level} {text}"

    @staticmethod
    def _is_list_node(node) -> bool:
        tag = str(getattr(node, "tag", "") or "").lower()
        if tag in {"ul", "ol"}:
            return True
        return bool(node.xpath("./li"))

    @staticmethod
    def _extract_list_block(node, *, depth: int = 0) -> str:
        tag = str(getattr(node, "tag", "") or "").lower()
        ordered = tag == "ol"
        items = node.xpath("./li")
        if not items:
            return ""
        lines: list[str] = []
        for idx, li in enumerate(items, start=1):
            prefix = f"{idx}. " if ordered else "- "
            indent = "  " * depth
            content = GeekbangAdapter._extract_list_item_text(li)
            if content:
                lines.append(f"{indent}{prefix}{content}")
            nested_lists = li.xpath("./ul|./ol")
            for nested in nested_lists:
                nested_text = GeekbangAdapter._extract_list_block(nested, depth=depth + 1)
                if nested_text:
                    lines.append(nested_text)
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_list_item_text(li_node) -> str:
        clone = deepcopy(li_node)
        for nested in clone.xpath(".//ul|.//ol|.//img|.//script|.//style"):
            parent = nested.getparent()
            if parent is not None:
                parent.remove(nested)
        return GeekbangAdapter._text_with_links(clone)

    @staticmethod
    def _is_table_node(node) -> bool:
        tag = str(getattr(node, "tag", "") or "").lower()
        if tag == "table":
            return True
        return bool(node.xpath(".//table"))

    @staticmethod
    def _extract_table_block(node) -> str:
        table = node
        if str(getattr(node, "tag", "") or "").lower() != "table":
            candidates = node.xpath(".//table")
            if not candidates:
                return ""
            table = candidates[0]

        rows: list[list[str]] = []
        header_by_th = False
        for tr in table.xpath(".//tr"):
            cells = tr.xpath("./th|./td")
            if not cells:
                continue
            if tr.xpath("./th"):
                header_by_th = True
            vals: list[str] = []
            for cell in cells:
                text = GeekbangAdapter._clean_text(cell.text_content())
                vals.append(text.replace("|", r"\|"))
            rows.append(vals)
        if not rows:
            return ""
        col_count = max(len(r) for r in rows)
        normalized_rows = [r + [""] * (col_count - len(r)) for r in rows]
        header = normalized_rows[0]
        body = normalized_rows[1:]
        if not header_by_th and not body:
            return ""
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * col_count) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines).strip()

    @staticmethod
    def _is_code_block_node(node) -> bool:
        tag = str(getattr(node, "tag", "") or "").lower()
        # Block-level code should be detected conservatively.
        if tag == "pre":
            return True
        class_attr = str(node.get("class") or "").lower()
        if any(token in class_attr for token in ("codeblock", "code-block", "hljs", "highlight", "language-")):
            return True
        # A descendant <pre> is a strong signal of block code.
        if node.xpath(".//pre"):
            return True
        return False

    @staticmethod
    def _extract_code_block(node) -> str:
        lang = GeekbangAdapter._detect_code_language(node)
        raw = (node.text_content() or "").replace("\u00a0", " ").replace("\u200b", "")
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in raw.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return ""
        if GeekbangAdapter._should_reflow_compact_code(lines, lang):
            reflowed = GeekbangAdapter._reflow_compact_code("\n".join(lines))
            if reflowed and len(reflowed) > len(lines):
                lines = reflowed
        if lines and lines[0].strip().startswith("```"):
            return "\n".join(lines).strip()
        fence = f"```{lang}" if lang else "```"
        return f"{fence}\n" + "\n".join(lines) + "\n```"

    @staticmethod
    def _detect_code_language(node) -> str:
        candidates = [
            str(node.get("data-language") or ""),
            str(node.get("data-lang") or ""),
            str(node.get("language") or ""),
            str(node.get("class") or ""),
        ]
        for item in candidates:
            low = item.lower()
            m = re.search(r"language-([a-z0-9_+-]+)", low)
            if m:
                return m.group(1)
            if low in {"python", "java", "javascript", "typescript", "go", "rust", "c", "cpp", "bash", "shell", "json", "yaml", "sql"}:
                return low
        return ""

    @staticmethod
    def _image_href(img_node) -> str:
        href_values = img_node.xpath("ancestor::a[1]/@href")
        href = str(href_values[0]).strip() if href_values else ""
        if href.startswith("//"):
            return "https:" + href
        return href

    @staticmethod
    def _should_reflow_compact_code(lines: list[str], lang: str) -> bool:
        if not lines:
            return False
        compact = [line for line in lines if line.strip()]
        if len(compact) > 2:
            return False
        joined = "\n".join(compact).strip()
        if len(joined) < 120:
            return False
        low = joined.lower()
        python_defs = len(re.findall(r"\b(def|class)\s+[a-zA-Z_][a-zA-Z0-9_]*", low))
        if python_defs < 2:
            python_defs = low.count("def ")
        if python_defs >= 2:
            return True
        score = 0
        for token in (
            ";",
            "{",
            "}",
            "=>",
            "function ",
            "const ",
            "let ",
            "var ",
            "return ",
            "if(",
            "if (",
            "for(",
            "for (",
            "while(",
            "while (",
            "import ",
            "class ",
            "def ",
        ):
            if token in low:
                score += 1
        if lang.lower() in {"javascript", "typescript", "java", "c", "cpp", "go", "rust", "python", "bash", "shell"}:
            score += 1
        return score >= 4

    @staticmethod
    def _reflow_compact_code(text: str) -> list[str]:
        source = (text or "").strip()
        if not source:
            return []
        source = re.sub(
            r"(?<!\n)\s+(def\s+[^\s\(]+\s*\()",
            r"\n\1",
            source,
        )
        source = re.sub(
            r"(?<!\n)(?<!\s)(def\s+[^\s\(]+\s*\()",
            r"\n\1",
            source,
        )
        source = re.sub(
            r"(?<!\n)\s+(class\s+[^\s\(:]+\s*[:\(])",
            r"\n\1",
            source,
        )
        source = re.sub(
            r"(?<!\n)(?<!\s)(class\s+[^\s\(:]+\s*[:\(])",
            r"\n\1",
            source,
        )
        source = re.sub(
            r"(?<!\n)\s+(if\s+__name__\s*==\s*['\"]__main__['\"]\s*:)",
            r"\n\1",
            source,
        )
        source = re.sub(
            r"(?<!\n)(?<!\s)(if\s+__name__\s*==\s*['\"]__main__['\"]\s*:)",
            r"\n\1",
            source,
        )

        lines: list[str] = []
        buf: list[str] = []
        indent = 0
        in_single = False
        in_double = False
        escape = False
        unit = "    "

        def flush_line(*, use_current_indent: bool = True) -> None:
            nonlocal buf
            item = "".join(buf).strip()
            buf = []
            if not item:
                return
            prefix = unit * (indent if use_current_indent else max(0, indent - 1))
            lines.append(prefix + item)

        for ch in source:
            if escape:
                buf.append(ch)
                escape = False
                continue
            if ch == "\\" and (in_single or in_double):
                buf.append(ch)
                escape = True
                continue
            if in_single:
                buf.append(ch)
                if ch == "'":
                    in_single = False
                continue
            if in_double:
                buf.append(ch)
                if ch == '"':
                    in_double = False
                continue
            if ch == "'":
                buf.append(ch)
                in_single = True
                continue
            if ch == '"':
                buf.append(ch)
                in_double = True
                continue

            if ch == "{":
                buf.append(ch)
                flush_line()
                indent += 1
                continue
            if ch == "}":
                flush_line()
                indent = max(0, indent - 1)
                lines.append((unit * indent) + "}")
                continue
            if ch == ";":
                if lines and lines[-1].rstrip().endswith("}") and not buf:
                    lines[-1] = lines[-1] + ";"
                else:
                    buf.append(ch)
                    flush_line()
                continue
            if ch == "\n":
                flush_line()
                continue
            buf.append(ch)

        flush_line()
        return [line for line in lines if line.strip()]

    @staticmethod
    def _render_compact_code_from_text(text: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return ""
        if not GeekbangAdapter._looks_like_compact_code_text(candidate):
            return ""
        lines = GeekbangAdapter._reflow_compact_code(candidate)
        if len(lines) <= 1:
            return ""
        return "```\n" + "\n".join(lines) + "\n```"

    @staticmethod
    def _looks_like_compact_code_text(text: str) -> bool:
        candidate = (text or "").strip()
        if len(candidate) < 180:
            return False
        low = candidate.lower()
        python_defs = len(re.findall(r"\b(def|class)\s+[a-zA-Z_][a-zA-Z0-9_]*", low))
        if python_defs < 2:
            python_defs = low.count("def ")
        if python_defs >= 2:
            return True
        score = 0
        for token in (
            ";",
            "{",
            "}",
            "=>",
            "function ",
            "const ",
            "let ",
            "var ",
            "return ",
            "if(",
            "if (",
            "for(",
            "for (",
            "while(",
            "while (",
            "import ",
        ):
            if token in low:
                score += 1
        return score >= 4

    @staticmethod
    def _is_decorative_image(node, src: str) -> bool:
        low_src = (src or "").lower()
        if any(
            key in low_src
            for key in (
                "/img/logo",
                "logo-normal",
                "empty-comment",
                "avatar",
                "robot",
                "chatbot",
                "assistant",
                "icon",
            )
        ):
            return True

        if node is not None:
            attrs = " ".join(
                str(node.get(k) or "")
                for k in ("class", "id", "alt", "title", "data-testid", "aria-label")
            ).lower()
            if any(
                key in attrs
                for key in ("logo", "avatar", "author", "chat", "robot", "assistant", "icon", "comment")
            ):
                return True

            for key in ("width", "height"):
                value = str(node.get(key) or "").strip().lower().replace("px", "")
                if value.isdigit() and int(value) <= 64:
                    return True

        return False

    @staticmethod
    def _filter_images_and_markers(body: str, images: list) -> tuple[str, list]:
        if not body or not images:
            return body, images
        kept: list[str] = []
        index_map: dict[int, int] = {}
        for old_idx, src in enumerate(images, start=1):
            image_src = GeekbangAdapter._image_src(src)
            if GeekbangAdapter._is_decorative_image(None, image_src):
                continue
            index_map[old_idx] = len(kept) + 1
            kept.append(src)
        if len(kept) == len(images):
            return body, images

        output_lines: list[str] = []
        for raw in body.splitlines():
            line = raw.strip()
            m_img = re.fullmatch(r"\[IMG:(\d+)\]", line)
            if m_img:
                new_idx = index_map.get(int(m_img.group(1)))
                if new_idx:
                    output_lines.append(f"[IMG:{new_idx}]")
                continue

            m_cap = re.fullmatch(r"\[IMG_CAPTION:(\d+)\](?:\s*(.*))?", line)
            if m_cap:
                new_idx = index_map.get(int(m_cap.group(1)))
                if new_idx:
                    caption = (m_cap.group(2) or "").strip()
                    output_lines.append(f"[IMG_CAPTION:{new_idx}] {caption}".rstrip())
                continue
            output_lines.append(raw)
        cleaned = "\n".join(output_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, kept

    @staticmethod
    def _image_src(image) -> str:
        if isinstance(image, dict):
            return str(image.get("src") or "").strip()
        return str(image or "").strip()

    @staticmethod
    def _normalize_image_entries(images: list) -> list[dict]:
        rows: list[dict] = []
        for raw in images or []:
            if isinstance(raw, dict):
                src = str(raw.get("src") or "").strip()
                alt = str(raw.get("alt") or "").strip()
                href = str(raw.get("href") or "").strip()
            else:
                src = str(raw or "").strip()
                alt = ""
                href = ""
            if not src:
                continue
            rows.append({"src": src, "alt": alt, "href": href})
        return rows

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
    def _text_with_links(node) -> str:
        raw_html = html.tostring(node, encoding="unicode", method="html")
        raw_html = re.sub(r"(?i)<br\s*/?>", "\n", raw_html)

        def _anchor_replace(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            inner = match.group(2) or ""
            href_match = re.search(r'href\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.IGNORECASE)
            href = href_match.group(1).strip() if href_match else ""
            if href.startswith("//"):
                href = "https:" + href
            text = re.sub(r"<[^>]+>", "", inner or "")
            text = std_html.unescape(text).strip()
            if href and text:
                return f"[{text}]({href})"
            return text

        raw_html = re.sub(r"(?is)<a\b([^>]*)>(.*?)</a>", _anchor_replace, raw_html)
        # Preserve inline code semantics inside normal text/list items.
        raw_html = re.sub(
            r"(?is)<code\b[^>]*>(.*?)</code>",
            lambda m: f"`{std_html.unescape(re.sub(r'<[^>]+>', '', m.group(1) or '')).strip()}`",
            raw_html,
        )
        plain = re.sub(r"(?is)<[^>]+>", "", raw_html)
        plain = std_html.unescape(plain)
        return GeekbangAdapter._clean_text(plain)

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
        text = (value or "").replace("\u00a0", " ").replace("\u200b", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            return ""
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
        in_fence = False
        for line in text.splitlines():
            item = line.strip()
            if item.startswith("```"):
                in_fence = not in_fence
                cleaned_lines.append("```" if item == "```" else item)
                continue
            if in_fence:
                cleaned_lines.append(line.rstrip())
                continue
            if not item:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
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
