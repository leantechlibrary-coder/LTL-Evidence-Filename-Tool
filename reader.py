"""
証拠リネームツール — 入力パーサ（貼り付け方式）

任意フォーマットのファイルを読み込んで列を推測する方式はやめ、
利用者がスプレッドシート等で「号証」「標目」の2列を選んでコピーし、
そのまま貼り付けたテキストを解釈する。クリップボード経由なら
Excel / スプレッドシート / Word の表 / CSV のいずれを写しても
タブ区切りテキストになるため、形式判定そのものが不要になる。

契約（貼り付けフォーマット）:
  1行 = 1号証。区切りはタブ推奨（2列選択コピーで自動的にタブ区切り）。
  タブが無ければ「2つ以上の連続空白」を列区切りとみなす。
  左が号証セル、右が標目。3列以上貼られても先頭2項目だけ使う。

吸収する揺らぎ:
  - 全角英数字は core 側で半角化（甲００１ → 甲001）。種別漢字は保持。
  - 種別と番号が別セルに割れている形式（"甲" | "1"）→ 連結して "甲1"。
  - 号証セルが空 + 標目だけ埋まる行（結合セルの継承）→ 直上号証を継承。

号証として解釈できない行（見出し・空行・当事者目録など）は自動で無視する。
"""

from __future__ import annotations

import re

import core

Grid = list[list[str]]

# 種別漢字（単独セルで来たら次の番号セルと連結する合図）
_SEIBETSU = ("甲", "乙", "丙", "丁")

# 番号セルの形（種別を除いた部分）。プレフィックス一致ではなく全体一致で、
# "2024年契約書" のような標目を番号と誤認しないようにする。
_BRANCH_SEP = "-ー‐−–—－の"
_NUMCELL_RE = re.compile(
    r"^\s*[A-Za-z]?\s*(?:第)?\s*[0-9]+\s*(?:号証)?"
    r"(?:\s*[" + _BRANCH_SEP + r"]\s*[0-9]+(?:\s*[~〜～]\s*[0-9]*)?)?\s*$"
)


# ---- フィールド分割 ----

def _split_fields(line: str) -> list[str]:
    """1行を列に割る。タブ最優先 → 2連続以上の空白 → 単一空白で2分割。"""
    s = line.rstrip("\r")
    if "\t" in s:
        return s.split("\t")
    multi = re.split(r"[ \u3000]{2,}", s.strip())
    if len(multi) >= 2:
        return multi
    # 単一空白しかない手入力のフォールバック（最初の空白で号証/標目に2分割）
    return re.split(r"[ \u3000]+", s.strip(), maxsplit=1)


def _is_number_cell(s: str) -> bool:
    return bool(_NUMCELL_RE.fullmatch(core.normalize_alnum(s)))


def _interpret(fields: list[str]) -> tuple[str, str]:
    """フィールド列から (号証セル, 標目) を取り出す。種別/番号分割を吸収。"""
    f = [x.strip() for x in fields]
    while f and not f[-1]:        # 末尾の空セルを落とす
        f.pop()
    if not f:
        return "", ""
    # "甲" | "1" | "標目..." → 号証セルを連結
    if len(f) >= 2 and f[0] in _SEIBETSU and _is_number_cell(f[1]):
        kosho = f[0] + f[1]
        hy = f[2] if len(f) >= 3 else ""
        return kosho, hy
    kosho = f[0]
    hy = f[1] if len(f) >= 2 else ""
    return kosho, hy


# ---- レコード抽出 ----

def records_from(grid: Grid, kosho_col: int, hyoumoku_col: int | None) -> list[tuple[str, str]]:
    """指定列から (番号セル, 標目) を抽出。号証として解釈できる行のみ＝見出し・空行は自動で除外。

    号証列が空でも、直前の号証行があり標目だけ埋まっている場合は
    結合セルの伝播とみなして直上の号証を継承する（甲3 の縦結合 → 甲3, 甲3...）。
    継承時は build_plan 側で重複として検出され、号証重複の警告になる。
    枝番付き（甲3-1, 甲3-2）が別行で正しく入っている通常ケースはそのまま通る。
    """
    recs: list[tuple[str, str]] = []
    last_kosho_cell = ""
    for row in grid:
        cell = row[kosho_col] if kosho_col < len(row) else ""
        hy = ""
        if hyoumoku_col is not None and hyoumoku_col < len(row):
            hy = row[hyoumoku_col]

        if core.is_kosho_cell(cell):
            last_kosho_cell = cell
            recs.append((cell, hy))
        elif not cell.strip() and last_kosho_cell and hy.strip():
            # 号証列が空 + 標目が埋まっている → 結合セルの継承
            recs.append((last_kosho_cell, hy))
    return recs


def parse_pasted(text: str) -> list[tuple[str, str]]:
    """貼り付けテキストを (号証セル, 標目) のリストに解釈する。

    各行を (号証セル, 標目) の2列グリッドへ正規化し、records_from に通す。
    これにより結合セル継承・見出し除外を既存ロジックと共有する。
    """
    grid: Grid = []
    for line in text.splitlines():
        if not line.strip():
            continue
        kosho, hy = _interpret(_split_fields(line))
        grid.append([kosho, hy])
    return records_from(grid, 0, 1)
