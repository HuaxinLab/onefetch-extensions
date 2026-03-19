from __future__ import annotations

from onefetch.adapters.base import BaseAdapter
from onefetch.http import create_async_client
from onefetch.models import NormalizedFeed


class ExampleAdapter(BaseAdapter):
    id = "example"
    priority = 280

    def supports(self, url: str) -> bool:
        return "example.com" in (url or "")

    async def crawl(self, url: str) -> NormalizedFeed:
        async with create_async_client(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        body = response.text.strip()
        return self._build_feed(
            source_url=url,
            canonical_url=url,
            title="Example",
            body=body,
            raw_body=response.text,
        )


def register() -> None:
    return None
