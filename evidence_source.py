"""
証拠説明書ファイルから (号証, 標目) を読む — xlsx / csv / docx 対応
=================================================================

貼り付け（parse_pasted）に加え、証拠説明書ファイルを直接指すための読み取り経路。
LLM経由の運用で、号証↔標目を pasted_text として渡すとタブが改行に化けるなど
壊れやすいのを避け、「ファイルパスを1つ渡すだけ」に単純化する狙い（決定論の徹底）。

対応:
  - .xlsx : openpyxl（唯一の追加依存, MIT）
  - .csv  : 標準ライブラリ csv（utf-8-sig → cp932 フォールバック）
  - .docx : 標準ライブラリ zipfile + xml（word/document.xml のテーブルを直接読む）

いずれも「行×セルのグリッド」へ正規化し、ヘッダ行（号証／標目）から列位置を検出、
既存の reader.records_from に通す。ヘッダが無ければ先頭2列（号証, 標目）とみなす。
号証として解釈できない行（見出し・空行・注記）は records_from 側で自動除外される。

サーバはネットワークに出ない。ファイルは読むだけで一切書き換えない。
"""

from __future__ import annotations

import os

import core
import reader

Grid = list[list[str]]

# docx（WordprocessingML）名前空間
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _cell(v) -> str:
    """セル値を文字列へ。None は空文字。前後空白と改行由来の空白は保持せず整える。"""
    if v is None:
        return ""
    return str(v).strip()


def _norm_header(s: str) -> str:
    """ヘッダ判定用の正規化：全角英数半角化＋全ての空白（半角/全角/改行）除去。"""
    t = core.normalize_alnum(str(s or ""))
    for ch in (" ", "　", "\n", "\r", "\t"):
        t = t.replace(ch, "")
    return t


def _detect_columns(grid: Grid) -> tuple[int, int, int]:
    """グリッドからヘッダ行を探し (号証列, 標目列, ヘッダ行index) を返す。
    見つからなければ (0, 1, -1)＝先頭2列を号証/標目とみなす。"""
    for i, row in enumerate(grid):
        norm = [_norm_header(c) for c in row]
        kcol = next((j for j, v in enumerate(norm) if v == "号証"), None)
        hcol = next((j for j, v in enumerate(norm) if v == "標目"), None)
        if kcol is not None and hcol is not None:
            return kcol, hcol, i
    return 0, 1, -1


def _grid_to_records(grid: Grid) -> list[tuple[str, str]]:
    """列検出→ヘッダ以降（無ければ全体）を records_from に通す。"""
    kcol, hcol, header_i = _detect_columns(grid)
    body = grid[header_i + 1:] if header_i >= 0 else grid
    return reader.records_from(body, kcol, hcol)


# ---- 各形式 → グリッド ----

def _xlsx_grid(path: str) -> Grid:
    import openpyxl  # 遅延import（GUI/paste経路には不要）
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.active
        return [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _csv_grid(path: str) -> Grid:
    import csv
    # 日本語CSVは utf-8(BOM) か cp932 が大半。順に試す。
    for enc in ("utf-8-sig", "cp932"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return [[_cell(c) for c in row] for row in csv.reader(f)]
        except UnicodeDecodeError:
            continue
    # 最後の砦：置換読みで壊さず通す
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return [[_cell(c) for c in row] for row in csv.reader(f)]


def _docx_grid(path: str) -> Grid:
    """word/document.xml のテーブルを標準ライブラリだけで読む（python-docx不要）。
    複数テーブルは行を連結。列検出でヘッダを拾うので混在しても号証表を選べる。"""
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    grid: Grid = []
    for tbl in root.iter(f"{_W}tbl"):
        for tr in tbl.iter(f"{_W}tr"):
            row: list[str] = []
            for tc in tr.iter(f"{_W}tc"):
                # セル内の全 w:t を連結（段落跨ぎも1セルとして）
                texts = [t.text or "" for t in tc.iter(f"{_W}t")]
                row.append(_cell("".join(texts)))
            if row:
                grid.append(row)
    return grid


_READERS = {".xlsx": _xlsx_grid, ".csv": _csv_grid, ".docx": _docx_grid}
SUPPORTED_EXTS = tuple(_READERS)


def read_records(path: str) -> list[tuple[str, str]]:
    """証拠説明書ファイル（xlsx/csv/docx）から (号証, 標目) のリストを読む。
    未対応拡張子・ファイル不在は ValueError。中身は一切書き換えない。"""
    p = os.path.abspath(os.path.expanduser(str(path).strip()))
    if not os.path.isfile(p):
        raise ValueError(f"ファイルが見つかりません: {p}")
    ext = os.path.splitext(p)[1].lower()
    fn = _READERS.get(ext)
    if fn is None:
        raise ValueError(f"未対応の形式です（{ext or '拡張子なし'}）。対応: {', '.join(SUPPORTED_EXTS)}")
    return _grid_to_records(fn(p))
