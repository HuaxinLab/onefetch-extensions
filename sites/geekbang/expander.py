from __future__ import annotations

import re
from urllib.parse import urlparse


class GeekbangCourseExpander:
    id = "geekbang_course"

    def supports(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        path = urlparse(url).path or ""
        return host == "b.geekbang.org" and path.startswith("/member/course/intro/")

    def discover(self, seed_url: str, html_text: str) -> list[str]:
        # 从课程页 HTML 中提取章节 detail ID（兼容 4/5/6 位）
        ids: list[str] = []
        text = html_text or ""

        for m in re.finditer(r'id="id(\d{4,})"', text):
            cid = m.group(1)
            if cid not in ids:
                ids.append(cid)

        for m in re.finditer(r"/member/course/detail/(\d{4,})", text):
            cid = m.group(1)
            if cid not in ids:
                ids.append(cid)
        return [f"https://b.geekbang.org/member/course/detail/{cid}" for cid in ids]
