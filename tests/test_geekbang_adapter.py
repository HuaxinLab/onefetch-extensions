from __future__ import annotations

import importlib.util
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import pytest
from lxml import html


def _require_onefetch_core() -> None:
    # Extension tests depend on OneFetch core modules imported by adapter.py.
    # Set ONEFETCH_CORE_PATH (preferred) or PYTHONPATH before running tests.
    core_path = os.getenv("ONEFETCH_CORE_PATH", "").strip()
    if core_path:
        core = Path(core_path).expanduser().resolve()
        if core.is_dir() and str(core) not in os.sys.path:
            os.sys.path.insert(0, str(core))

    try:
        import onefetch  # noqa: F401
    except Exception as exc:
        pytest.skip(f"onefetch core not importable; set ONEFETCH_CORE_PATH/PYTHONPATH ({exc})")


@lru_cache(maxsize=1)
def _load_geekbang_adapter_class():
    _require_onefetch_core()
    root = Path(__file__).resolve().parents[1]
    path = root / "sites" / "geekbang" / "adapter.py"
    if not path.is_file():
        pytest.skip(f"geekbang adapter not found: {path}")
    spec = importlib.util.spec_from_file_location("ext_geekbang_adapter", path)
    if spec is None or spec.loader is None:
        pytest.skip(f"failed to load geekbang adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter_cls = getattr(module, "GeekbangAdapter", None)
    if adapter_cls is None:
        pytest.skip("GeekbangAdapter class not found")
    return adapter_cls


def test_detail_extracts_author_published_and_image_caption() -> None:
    adapter_cls = _load_geekbang_adapter_class()
    tree = html.fromstring(
        """
        <html><body>
          <div class="ArticleContent_audio-course-wrapper_251E1">
            <h1 class="ArticleContent_title_1GKta">开篇词｜共生而非替代：极客和 AI 的共舞</h1>
            <div class="ArticleContent_desc_17GmP">黄佳</div>
            <p class="ArticleContent_first-publish_3y0sJ">2026-01-27</p>
            <div class="ProseMirror">
              <p>你好，我是黄佳。</p>
              <div><img src="https://static001.geekbang.org/resource/a.png"/><p>图片说明文案</p></div>
              <p>课程代码仓库链接：https://github.com/huangjia2019/claude-code-engingeering</p>
            </div>
          </div>
          <div class="CatalogPC_wrapper_1s8lY">课程目录 噪音</div>
        </body></html>
        """
    )
    payload = adapter_cls._extract_detail_content(tree)
    assert payload is not None
    assert payload["title"] == "开篇词｜共生而非替代：极客和 AI 的共舞"
    assert payload["author"] == "黄佳"
    assert payload["published_at"] is not None
    assert payload["published_at"].utcoffset() == timedelta(hours=8)
    assert "你好，我是黄佳。" in payload["body"]
    assert "[IMG:1]" in payload["body"]
    assert "[IMG_CAPTION:1] 图片说明文案" in payload["body"]
    assert "课程目录 噪音" not in payload["body"]
    assert payload["images"] == ["https://static001.geekbang.org/resource/a.png"]


def test_cleanup_filters_known_noise_lines() -> None:
    adapter_cls = _load_geekbang_adapter_class()
    raw = """
    We're sorry but member.b.geekbang.com doesn't work properly without JavaScript enabled.
    Please enable it to continue.
    问好
    
    
    正文第一段
    (function(win, export_obj) {
    win['LogAnalyticsObject'] = export_obj;
    _collect.q = _collect.q || [];
    })(window, 'collectEvent');
    正文第二段
    """
    cleaned = adapter_cls._cleanup_body(raw)
    assert "without JavaScript enabled" not in cleaned
    assert "Please enable it to continue" not in cleaned
    assert "问好" not in cleaned
    assert "LogAnalyticsObject" not in cleaned
    assert "collectEvent" not in cleaned
    assert "正文第一段" in cleaned
    assert "正文第二段" in cleaned


def test_intro_extracts_article_typo_content() -> None:
    adapter_cls = _load_geekbang_adapter_class()
    tree = html.fromstring(
        """
        <html><body>
          <div class="ColumnInfoPC_column-title">Claude Code 工程化实战</div>
          <div class="ColumnInfoPC_teacher">黄佳</div>
          <div class="IntroPC_intro-wrapper_47Uxf">
            <div class="article-typo">
              <p>课程介绍第一段</p>
              <p>课程介绍第二段</p>
            </div>
            <div class="IntroPC_intro-item_qEeA5">课程目录（噪音）</div>
          </div>
        </body></html>
        """
    )
    payload = adapter_cls._extract_intro_content(tree)
    assert payload is not None
    assert payload["title"] == "Claude Code 工程化实战"
    assert payload["author"] == "黄佳"
    assert payload["published_at"] is None
    assert "课程介绍第一段" in payload["body"]
    assert "课程介绍第二段" in payload["body"]
