"""合成フィクスチャ。PyQt は使わず core / reader / mcp_server だけを叩く。"""
import os
import sys

import pytest
from pypdf import PdfWriter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_pdf(path, pages=1):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        w.write(f)


@pytest.fixture
def rename_dir(tmp_path):
    """号証フォルダ＋貼り付けテンプレ（号証[Tab]標目）。"""
    d = tmp_path / "rename_src"
    d.mkdir()
    for nm in ("甲1号証.pdf", "甲2号証.pdf", "乙A1号証.pdf"):
        _make_pdf(d / nm)
    template = "号証\t標目\n甲1\t請求書\n甲2\t領収書\n乙A1\t契約書\n"
    return d, template


@pytest.fixture
def branch_dir(tmp_path):
    """枝番束（stamp の出力を模した 甲001-1 / 甲001-2）。"""
    d = tmp_path / "branch_src"
    d.mkdir()
    _make_pdf(d / "甲001-1.pdf")
    _make_pdf(d / "甲001-2.pdf")
    return d
