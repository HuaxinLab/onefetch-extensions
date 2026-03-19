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
        # 示例实现：从课程页 HTML 中提取 detail ID 并生成章节 URL
        ids = []
        for m in re.finditer(r'id="id(\d{5,})"', html_text or ""):
            cid = m.group(1)
            if cid not in ids:
                ids.append(cid)
        return [f"https://b.geekbang.org/member/course/detail/{cid}" for cid in ids]
