"""内蔵MCP（rename）の契約＋スモークテスト。PyQt 非依存。"""
import asyncio
import csv
import os
import zipfile

from pypdf import PdfReader

import core
import reader
import evidence_source as ES
import mcp_server as M


# ---- 証拠説明書ファイル読み取り（xlsx / csv / docx）ヘルパ ----

def _make_xlsx(path, rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(list(r))
    wb.save(str(path))


def _make_csv(path, rows, encoding="utf-8-sig"):
    with open(path, "w", newline="", encoding=encoding) as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(list(r))


def _make_docx(path, rows):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    def tc(t):
        return f"<w:tc><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:tc>"
    def tr(cells):
        return "<w:tr>" + "".join(tc(c) for c in cells) + "</w:tr>"
    body = "".join(tr(r) for r in rows)
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
           f"<w:tbl>{body}</w:tbl></w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", doc)


# ---- 貼り付けパーサ: LLMがタブを改行に化けさせた入力の復元 ----

def test_parse_pasted_recovers_newline_mangled_pairs():
    # gemma等がタブ→改行に化けさせ、号証と標目が1行ずつ交互に並ぶケース
    mangled = "甲1\n賃貸借契約書\n甲2\n重要事項説明書\n甲3\n解除通知書"
    assert reader.parse_pasted(mangled) == [
        ("甲1", "賃貸借契約書"), ("甲2", "重要事項説明書"), ("甲3", "解除通知書"),
    ]


def test_parse_pasted_tab_and_space_unaffected():
    # 正規のタブ貼り付け・スペース区切り手入力は復元ロジックに影響されない
    assert reader.parse_pasted("甲1\t契約書\n甲2\t請求書") == [("甲1", "契約書"), ("甲2", "請求書")]
    assert reader.parse_pasted("甲1 契約書\n甲2 請求書") == [("甲1", "契約書"), ("甲2", "請求書")]


def test_parse_pasted_no_false_recovery():
    # 号証のみ（標目なし）は復元せず空のまま。奇数・不完全も復元しない（誤発火防止）
    assert reader.parse_pasted("甲1\n甲2\n甲3") == [("甲1", ""), ("甲2", ""), ("甲3", "")]
    assert reader.parse_pasted("甲1\n契約書\n甲2") == [("甲1", ""), ("甲2", "")]


# ---- 正規形フォーマット契約（stamp アプリとの越境相互運用の要）----

def test_canonical_filename_format():
    assert core.build_filename(core.Kosho("甲", 5), "標目") == "甲005 標目.pdf"
    assert core.build_filename(core.Kosho("甲", 1, branch=2), "見積") == "甲001-2 見積.pdf"
    assert core.build_filename(core.Kosho("乙", 1, kigou="A"), "契約") == "乙A001 契約.pdf"


def test_parse_kosho_contract_and_tilde_fix():
    assert core.parse_kosho("甲005 標目.pdf").key() == ("甲", "", 5, None)
    assert core.parse_kosho("乙A001-1 契約.pdf").key() == ("乙", "A", 1, 1)
    # 標目内チルダは弾かない（旧 None → 修正後 認識）
    assert core.parse_kosho("甲005 取引明細（令和5年～6年）.pdf").key() == ("甲", "", 5, None)
    # 範囲表記は parse_kosho では None（parse_range 担当）
    assert core.parse_kosho("甲001-1~2 一括.pdf") is None
    assert core.parse_kosho("メモ.pdf") is None


# ---- MCP ツール登録（2本：plan/executeを統合）----

def test_mcp_registers_two_rename_tools():
    names = sorted(t.name for t in asyncio.run(M.mcp.list_tools()))
    assert names == ["rename_execute", "rename_folder_stats"]


# ---- dry_run: 計画のみ返し、書き込みしない ----

def test_dry_run_returns_plan_without_writing(rename_dir):
    d, tmpl = rename_dir
    res = M.rename_execute(str(d), tmpl, dry_run=True)
    assert res["executed"] is False
    assert res["records_parsed"] == 3
    assert res["counts"].get("リネーム") == 3
    assert res["warnings"] == []
    assert res["plan"][0]["new_name"].startswith("甲001")
    assert "output_dir" not in res
    assert len(list(d.glob("*.pdf"))) == 3  # 原本不変（書き込みなし）


# ---- warnings が無ければ force なしでも自動実行 ----

def test_rename_execute_outputs_and_source_intact(rename_dir):
    d, tmpl = rename_dir
    res = M.rename_execute(str(d), tmpl)
    assert res["executed"] is True
    assert res["succeeded"] == 3 and res["failed"] == 0
    assert os.path.isdir(res["output_dir"])
    assert d.name + "_提出用" in os.path.basename(res["output_dir"])
    assert len(list(d.glob("*.pdf"))) == 3        # 原本不変


# ---- warnings があれば force なしでは実行しない ----

def test_warnings_block_execution_without_force(rename_dir):
    d, tmpl = rename_dir
    bad_tmpl = tmpl + "甲9\t存在しない\n"  # 対応PDFが無い→ warning
    res = M.rename_execute(str(d), bad_tmpl)
    assert res["executed"] is False
    assert res["warnings"]
    assert "output_dir" not in res
    assert len(list(d.glob("*.pdf"))) == 3  # 原本不変


def test_warnings_execute_with_force(rename_dir):
    d, tmpl = rename_dir
    bad_tmpl = tmpl + "甲9\t存在しない\n"
    res = M.rename_execute(str(d), bad_tmpl, force=True)
    assert res["executed"] is True
    assert res["succeeded"] == 3   # 甲9はPDFなしで出力対象外、他3件は実行される


# ---- 枝番フロー end-to-end（stamp 出力の結合・継ぎ目の実証）----

def test_branch_bundle_merges(branch_dir):
    res = M.rename_execute(str(branch_dir), "甲1-1~2\t診断書\n")
    assert res["executed"] is True
    assert res["failed"] == 0
    merged = os.path.join(res["output_dir"], "甲001-1~2 診断書.pdf")
    assert os.path.isfile(merged)
    assert len(PdfReader(merged).pages) == 2       # 甲001-1 + 甲001-2 が1ファイルに


# ---- 証拠説明書ファイル読み取り（xlsx/csv/docx）----

_EVIDENCE_ROWS = [
    ["※注記行（民訴231条の2 …）"],
    ["号証", "標　目", "作成者"],            # 標目は全角スペース入りヘッダ
    ["甲1", "賃貸借契約書", "○○不動産"],
    ["甲2", "重要事項説明書", "○○不動産"],
    ["乙A1", "契約書", "被告"],
]
_EXPECT = [("甲1", "賃貸借契約書"), ("甲2", "重要事項説明書"), ("乙A1", "契約書")]


def test_source_read_xlsx(tmp_path):
    p = tmp_path / "証拠説明書.xlsx"
    _make_xlsx(p, _EVIDENCE_ROWS)
    assert ES.read_records(str(p)) == _EXPECT


def test_source_read_csv_utf8_and_cp932(tmp_path):
    p1 = tmp_path / "u.csv"
    _make_csv(p1, _EVIDENCE_ROWS, encoding="utf-8-sig")
    assert ES.read_records(str(p1)) == _EXPECT
    p2 = tmp_path / "s.csv"
    _make_csv(p2, [["号証", "標目"], ["甲1", "診断書"]], encoding="cp932")
    assert ES.read_records(str(p2)) == [("甲1", "診断書")]


def test_source_read_docx(tmp_path):
    p = tmp_path / "証拠説明書.docx"
    _make_docx(p, _EVIDENCE_ROWS)
    assert ES.read_records(str(p)) == _EXPECT


def test_source_read_unsupported_and_missing(tmp_path):
    import pytest
    txt = tmp_path / "note.txt"
    txt.write_text("号証\t標目\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ES.read_records(str(txt))            # 未対応拡張子
    with pytest.raises(ValueError):
        ES.read_records(str(tmp_path / "no_such.xlsx"))  # 不在


# ---- パス吸収（小型モデルが崩す表記の救済）----

def test_clean_path_normalizes_llm_mess():
    c = M._clean_path
    assert c("C:\\Users\\user\\a") == "C:/Users/user/a"       # バックスラッシュ
    assert c('  "C:/Users/user/a"  ') == "C:/Users/user/a"    # 引用符＋前後空白
    assert c("'C:/Users/user/a'") == "C:/Users/user/a"        # 単一引用符
    assert c("C:／Users／user") == "C:/Users/user"           # 全角スラッシュ
    assert c("　C:/Users/user　") == "C:/Users/user"          # 全角空白
    assert c("file:///C:/Users/user/a") == "C:/Users/user/a"  # file:///
    assert c("file://C:/Users/user/a") == "C:/Users/user/a"   # file://
    # 区切り直後の余計な空白（gemmaが挿入）を成分ごとに除去。内部空白は保持。
    assert c("C:/Users/user/ Documents/a.xlsx") == "C:/Users/user/Documents/a.xlsx"
    assert c("C:/Users/user /Documents/a.xlsx") == "C:/Users/user/Documents/a.xlsx"
    assert c("C:/My Reports/2024 evidence/a.xlsx") == "C:/My Reports/2024 evidence/a.xlsx"


def test_check_dir_accepts_messy_folder(rename_dir):
    d, _ = rename_dir
    messy = '"' + str(d).replace("/", "\\") + '"'   # バックスラッシュ＋引用符で包む
    res = M.rename_folder_stats(messy)
    assert res.get("total_pdfs") == 3


def test_source_path_accepts_messy(rename_dir, tmp_path):
    d, _ = rename_dir
    src = tmp_path / "説明書.xlsx"
    _make_xlsx(src, [["号証", "標目"], ["甲1", "請求書"], ["甲2", "領収書"], ["乙A1", "契約書"]])
    messy = str(src).replace("/", "\\")
    res = M.rename_execute(str(d), source_path=messy, dry_run=True)
    assert res["executed"] is False
    assert res["counts"].get("リネーム") == 3


# ---- rename_execute × source_path 統合 ----

def test_rename_execute_via_source_path(rename_dir, tmp_path):
    d, _ = rename_dir            # 甲1号証.pdf / 甲2号証.pdf / 乙A1号証.pdf
    src = tmp_path / "説明書.xlsx"
    _make_xlsx(src, [["号証", "標目"], ["甲1", "請求書"], ["甲2", "領収書"], ["乙A1", "契約書"]])
    res = M.rename_execute(str(d), source_path=str(src), dry_run=True)
    assert res["executed"] is False
    assert res["counts"].get("リネーム") == 3
    assert res["plan"][0]["new_name"] == "甲001 請求書.pdf"


def test_rename_execute_source_and_paste_conflict(rename_dir, tmp_path):
    d, tmpl = rename_dir
    src = tmp_path / "説明書.xlsx"
    _make_xlsx(src, [["号証", "標目"], ["甲1", "請求書"]])
    res = M.rename_execute(str(d), pasted_text=tmpl, source_path=str(src))
    assert "error" in res and "どちらか一方" in res["error"]


def test_rename_execute_requires_some_input(rename_dir):
    d, _ = rename_dir
    res = M.rename_execute(str(d))
    assert "error" in res
