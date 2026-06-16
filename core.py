"""
証拠リネームツール — 核ロジック（Slice 1〜4）

号証キー: (種別, 記号, 本番号, 枝番)
  - 種別: 甲乙丙丁
  - 記号: "" または A..Z（乙A 等。被告複数時。種別=甲と同等に扱う）
  - 本番号: int
  - 枝番: int または None

出力(mints正規形):
  甲005 標目.pdf / 乙A001 標目.pdf / 甲003-1 標目.pdf / 乙A001-1 標目.pdf
  （本番号は半角3桁ゼロ埋め、記号は種別直後、枝番は半角ハイフン）

設計:
  - 連番を仮定せず突き合わせのみ（追加提出対応）
  - 出力名は毎回テンプレから正規生成 → 二重リネームは構造的に発生しない
  - 読みは緩く（全角・枝番区切りゆらぎ吸収）、書きは正規形に潰す
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# mints禁止文字（公式手引には未記載だが、Windowsファイル名として必須のサニタイズ）
FORBIDDEN = r'\/:*?"<>|'
FORBIDDEN_RE = re.compile("[" + re.escape(FORBIDDEN) + "]")

# 全角英数字 → 半角（英数字のみ。かな・漢字・約物は保持）
_FW_ALNUM: dict[int, int] = {}
for _i in range(10):
    _FW_ALNUM[ord("０") + _i] = ord("0") + _i
for _i in range(26):
    _FW_ALNUM[ord("Ａ") + _i] = ord("A") + _i
    _FW_ALNUM[ord("ａ") + _i] = ord("a") + _i


def normalize_alnum(text: str) -> str:
    """全角の英数字だけを半角化する（種別漢字・かな・約物は保持）。"""
    return str(text).translate(_FW_ALNUM)


# 枝番区切りのゆらぎ: ハイフン各種 / 長音 / の。'-' は先頭に置く。
_BRANCH_SEP = "-ー‐−–—－の"
# 種別 + 記号(A-Z) + (第) + 本番号 + (号証) + (枝番区切り + 枝番)
_KOSHO_RE = re.compile(
    r"^\s*([甲乙丙丁])\s*([A-Za-z]?)\s*(?:第)?\s*0*([0-9]+)\s*(?:号証)?"
    r"(?:\s*[" + _BRANCH_SEP + r"]\s*0*([0-9]+))?"
)
# 範囲枝番（甲001-1~20 等）は未対応。検出したら拾わない。
_RANGE_MARK = ("~", "〜", "～")


@dataclass(frozen=True)
class Kosho:
    """号証キー。後方互換のため seibetsu, number を先頭に置く。"""
    seibetsu: str            # 甲乙丙丁
    number: int              # 本番号
    kigou: str = ""          # "" or A..Z
    branch: int | None = None  # 枝番 or None

    def key(self) -> tuple[str, str, int, int | None]:
        return (self.seibetsu, self.kigou, self.number, self.branch)

    def label(self) -> str:
        s = f"{self.seibetsu}{self.kigou}第{self.number}号証"
        if self.branch is not None:
            s += f"の{self.branch}"
        return s


def parse_kosho(text: str) -> Kosho | None:
    """ファイル名やテンプレの番号セルから号証キーを抽出。取れなければ None。

    全角→半角、枝番区切りゆらぎ（の/-/ー/‐/−/－）を吸収。
    範囲枝番（甲001-1~20）は未対応として None を返す。
    """
    if not text:
        return None
    norm = normalize_alnum(str(text))
    if any(m in norm for m in _RANGE_MARK):
        return None
    m = _KOSHO_RE.match(norm)
    if not m:
        return None
    branch = int(m.group(4)) if m.group(4) else None
    return Kosho(
        seibetsu=m.group(1),
        number=int(m.group(3)),
        kigou=m.group(2).upper(),
        branch=branch,
    )


# 範囲表記（甲001-1~2 等）。枝番区切り＋チルダ各種。標目は号証セルに含めない前提。
_RANGE_RE = re.compile(
    r"^\s*([甲乙丙丁])\s*([A-Za-z]?)\s*(?:第)?\s*0*([0-9]+)\s*(?:号証)?"
    r"\s*[" + _BRANCH_SEP + r"]\s*0*([0-9]+)"      # lo 枝番
    r"\s*[~〜～]\s*0*([0-9]*)"                        # ~ hi 枝番（空＝開いた表記）
)


@dataclass(frozen=True)
class KoshoRange:
    """範囲表記の号証束。甲001-1~2 → seibetsu=甲, number=1, lo=1, hi=2。
    hi が None のときは開いた表記（甲001-1~）＝lo 以降の存在分をすべて束ねる。"""
    seibetsu: str
    number: int
    kigou: str = ""
    lo: int = 1
    hi: int | None = None

    @property
    def open_ended(self) -> bool:
        return self.hi is None

    def branch_keys(self) -> list[tuple[str, str, int, int | None]]:
        """閉じた範囲の枝番キー列（lo..hi）。開いた表記では使わない。"""
        if self.hi is None:
            return []
        return [(self.seibetsu, self.kigou, self.number, b)
                for b in range(self.lo, self.hi + 1)]


def parse_range(text: str) -> KoshoRange | None:
    """範囲表記（甲001-1~2 / 甲001-1～ 等）を解釈。範囲でなければ None。"""
    if not text:
        return None
    norm = normalize_alnum(str(text))
    if not any(m in norm for m in _RANGE_MARK):
        return None
    m = _RANGE_RE.match(norm)
    if not m:
        return None
    hi_raw = m.group(5)
    return KoshoRange(
        seibetsu=m.group(1),
        number=int(m.group(3)),
        kigou=m.group(2).upper(),
        lo=int(m.group(4)),
        hi=int(hi_raw) if hi_raw else None,
    )


def parse_cell(text: str) -> "Kosho | KoshoRange | None":
    """号証セルを解釈。単独なら Kosho、範囲表記なら KoshoRange、どちらでもなければ None。"""
    k = parse_kosho(text)
    if k is not None:
        return k
    return parse_range(text)


def is_kosho_cell(text: str) -> bool:
    """単独・範囲いずれかの号証として解釈できるか（列検出・行抽出の判定用）。"""
    return parse_cell(text) is not None


def sanitize_hyoumoku(hyoumoku: str) -> str:
    """標目の禁止文字を除去し前後空白を整える。"""
    return FORBIDDEN_RE.sub("", str(hyoumoku)).strip()


def build_filename(kosho: Kosho, hyoumoku: str) -> str:
    """mints正規形のファイル名を生成。標目の全角英数字は半角化。"""
    h = sanitize_hyoumoku(normalize_alnum(hyoumoku))
    base = f"{kosho.seibetsu}{kosho.kigou}{kosho.number:03d}"
    if kosho.branch is not None:
        base += f"-{kosho.branch}"
    return f"{base} {h}.pdf" if h else f"{base}.pdf"


def build_range_filename(seibetsu: str, kigou: str, number: int,
                         lo: int, hi: int | None, hyoumoku: str,
                         open_ended: bool = False) -> str:
    """結合束のmints正規形ファイル名。範囲は半角チルダ。
    open_ended=True または hi が None なら 甲001-1~ の開いた表記。"""
    base = f"{seibetsu}{kigou}{number:03d}"
    if open_ended or hi is None:
        rng = f"{base}-{lo}~"
    elif lo == hi:
        rng = f"{base}-{lo}"          # 範囲だが実質1点
    else:
        rng = f"{base}-{lo}~{hi}"
    h = sanitize_hyoumoku(normalize_alnum(hyoumoku))
    return f"{rng} {h}.pdf" if h else f"{rng}.pdf"


# ---- 照合 ----

STATUS_RENAME = "rename"          # テンプレに行があり、PDFもある（通常）
STATUS_MERGE = "merge"            # 範囲表記の束を結合する（複数ソース→1出力）
STATUS_NO_PDF = "no_pdf"          # テンプレに行があるのにPDFが無い／束が欠けている（警告）
STATUS_NOT_IN_TEMPLATE = "skip"   # PDFはあるがテンプレに行が無い（対象外）
STATUS_COLLISION = "collision"    # 号証重複・生成名衝突（要確認）

WARN_STATUSES = (STATUS_NO_PDF, STATUS_COLLISION)


@dataclass
class Plan:
    status: str
    kosho: Kosho | None
    hyoumoku: str
    current_path: str | None
    current_name: str | None
    new_name: str | None
    source_paths: list[str] | None = None  # 結合時の元ファイル群（枝番順）

    @property
    def will_rename(self) -> bool:
        return self.status == STATUS_RENAME

    @property
    def will_merge(self) -> bool:
        return self.status == STATUS_MERGE

    @property
    def will_output(self) -> bool:
        return self.status in (STATUS_RENAME, STATUS_MERGE)


def scan_pdfs(folder: str) -> dict[tuple, tuple[Kosho, str]]:
    """フォルダ内のPDFを号証キー→(Kosho, 絶対パス)で返す。号証が取れないものは無視。"""
    result: dict[tuple, tuple[Kosho, str]] = {}
    for name in os.listdir(folder):
        if not name.lower().endswith(".pdf"):
            continue
        k = parse_kosho(name)
        if k is None:
            continue
        result[k.key()] = (k, os.path.join(folder, name))
    return result


def folder_pdf_stats(folder: str) -> tuple[int, int]:
    """フォルダ直下の (PDF総数, 号証として読めるPDF数) を返す。
    フォルダ選択直後の事前チェック用。サブフォルダは見ない（scan_pdfs と同じ範囲）。
    """
    total = 0
    recognizable = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return (0, 0)
    for name in names:
        if not name.lower().endswith(".pdf"):
            continue
        total += 1
        if parse_kosho(name) is not None:
            recognizable += 1
    return (total, recognizable)


def _collect_open_branches(pdf_map: dict, kr: KoshoRange) -> list[tuple]:
    """開いた表記（甲001-1~）: 同一号証で枝番 >= lo のキーを枝番順に集める。"""
    found = [
        key for key in pdf_map
        if key[0] == kr.seibetsu and key[1] == kr.kigou
        and key[2] == kr.number and key[3] is not None and key[3] >= kr.lo
    ]
    return sorted(found, key=lambda k: k[3])


def build_plan(folder: str, records: list[tuple[str, str]]) -> list[Plan]:
    """計画を作る（実行しない）。records: [(番号セル, 標目), ...]
    単独号証はリネーム、範囲表記（甲001-1~2）は結合プランにする。"""
    pdf_map = scan_pdfs(folder)
    matched_keys: set[tuple] = set()
    seen_record_keys: set[tuple] = set()
    new_name_owner: dict[str, str] = {}
    plans: list[Plan] = []

    for num_cell, hyoumoku in records:
        parsed = parse_cell(num_cell)
        if parsed is None:
            continue

        # ---- 範囲表記（結合） ----
        if isinstance(parsed, KoshoRange):
            kr = parsed
            rkey = (kr.seibetsu, kr.kigou, kr.number, kr.lo, kr.hi)
            if rkey in seen_record_keys:
                plans.append(Plan(STATUS_COLLISION, None, hyoumoku, None,
                                  f"{kr.seibetsu}{kr.kigou}{kr.number:03d}-{kr.lo}~", None))
                continue
            seen_record_keys.add(rkey)

            if kr.open_ended:
                # 開いた表記＝lo以降の存在分をすべて束ねる（飛び番フォールバックの出口）
                ordered = _collect_open_branches(pdf_map, kr)
                missing: list[int] = []
                open_out = True
            else:
                # 閉じた範囲＝lo..hi が全部そろって初めて結合（欠けは結合しない）
                ordered, missing = [], []
                for key in kr.branch_keys():
                    if key in pdf_map:
                        ordered.append(key)
                    else:
                        missing.append(key[3])
                open_out = False

            label = (f"{kr.seibetsu}{kr.kigou}{kr.number:03d}-{kr.lo}~"
                     + ("" if kr.hi is None else str(kr.hi)))

            if not ordered or missing:
                # 束が空 or 一部欠落 → 警告。結合しない（証拠の取りこぼし防止）。
                note = label if not missing else f"{label}（欠番: {','.join(map(str, missing))}）"
                plans.append(Plan(STATUS_NO_PDF, None, hyoumoku, None, note, None))
                continue

            source_paths = [pdf_map[k][1] for k in ordered]
            for k in ordered:
                matched_keys.add(k)
            hi_out = ordered[-1][3] if open_out else kr.hi
            new_name = build_range_filename(
                kr.seibetsu, kr.kigou, kr.number, kr.lo, hi_out, hyoumoku,
                open_ended=open_out,
            )
            current_name = "、".join(os.path.basename(p) for p in source_paths)

            lower = new_name.lower()
            if lower in new_name_owner:
                plans.append(Plan(STATUS_COLLISION, None, hyoumoku, None, current_name, new_name))
                continue
            new_name_owner[lower] = source_paths[0]

            plans.append(Plan(STATUS_MERGE, None, hyoumoku, None, current_name,
                              new_name, source_paths=source_paths))
            continue

        # ---- 単独号証（リネーム） ----
        kosho = parsed
        key = kosho.key()
        if key in seen_record_keys:
            plans.append(Plan(STATUS_COLLISION, kosho, hyoumoku, None, None, None))
            continue
        seen_record_keys.add(key)

        entry = pdf_map.get(key)
        if entry is None:
            plans.append(Plan(STATUS_NO_PDF, kosho, hyoumoku, None, None, None))
            continue

        _, path = entry
        matched_keys.add(key)
        current_name = os.path.basename(path)
        new_name = build_filename(kosho, hyoumoku)

        lower = new_name.lower()
        if lower in new_name_owner and new_name_owner[lower] != path:
            plans.append(Plan(STATUS_COLLISION, kosho, hyoumoku, path, current_name, new_name))
            continue
        new_name_owner[lower] = path

        plans.append(Plan(STATUS_RENAME, kosho, hyoumoku, path, current_name, new_name))

    # テンプレに無いPDF = 対象外（結合に消費された枝番は matched 済みなので出ない）
    for key, (kosho, path) in pdf_map.items():
        if key not in matched_keys:
            plans.append(Plan(STATUS_NOT_IN_TEMPLATE, kosho, "", path, os.path.basename(path), None))

    return plans


def _unique_output_dir(src_folder: str, suffix: str = "_提出用") -> str:
    """（親フォルダ名）_提出用 を src_folder の隣に作る。衝突時は _2, _3...。"""
    src_folder = os.path.abspath(src_folder)
    parent = os.path.dirname(src_folder)
    base = os.path.basename(src_folder) + suffix
    candidate = os.path.join(parent, base)
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(parent, f"{base}_{n}")
        n += 1
    return candidate


def _merge_pdfs(source_paths: list[str], dest: str) -> None:
    """枝番束を1ファイルに結合（ページ連結）。pypdf を使用。"""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for p in source_paths:
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)
    with open(dest, "wb") as f:
        writer.write(f)


def execute(plans: list[Plan], src_folder: str) -> tuple[list[tuple[Plan, bool, str]], str]:
    """提出物一式を（親フォルダ名）_提出用 に生成する。元フォルダは一切変更しない。
    - 単独号証: 原本を正規名でコピー
    - 範囲表記: 枝番束を結合して範囲名で出力
    提出用フォルダにはPDFのみを出力する（mints誤アップロード防止のため証跡ファイルは置かない）。
    戻り値: (各プランの結果, 出力フォルダの絶対パス)
    """
    import shutil

    out_dir = _unique_output_dir(src_folder)
    os.makedirs(out_dir, exist_ok=True)
    results: list[tuple[Plan, bool, str]] = []

    for p in plans:
        if not p.will_output:
            continue
        assert p.new_name
        dest = os.path.join(out_dir, p.new_name)
        try:
            if p.will_merge:
                assert p.source_paths
                _merge_pdfs(p.source_paths, dest)
                results.append((p, True, "結合完了"))
            else:
                assert p.current_path
                shutil.copy2(p.current_path, dest)
                results.append((p, True, "リネーム完了"))
        except (OSError, Exception) as e:  # noqa: BLE001 - PDF破損等も含めて1件失敗で止めない
            results.append((p, False, f"失敗: {e}"))

    return results, out_dir

