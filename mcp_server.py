"""
証拠ファイル名変換ツール — MCPサーバ（内蔵）
=============================================

GUI（app.py）と同じ決定論コア（core.py / reader.py）を共有し、号証リネームの
決定論部分を MCP ツールとして公開する。サーバはLLMを呼ばず、ネットワークにも
出ない。原本フォルダは不変、出力は隣の「(元フォルダ名)_提出用」へ。

公開ツール（2本）:
  rename_folder_stats : フォルダ直下PDF総数と号証認識数（事前の健全性確認）
  rename_execute       : 号証↔標目（pasted_text の貼り付け、または証拠説明書ファイル
                         source_path=xlsx/csv/docx）から計画（ドライラン相当）を作り、
                         warnings が無ければそのまま mints 正規名で出力する（plan/execute統合）。
                         dry_run=True で常に計画のみ、force=True で warnings があっても実行を強制。
                         範囲表記（甲001-1~2）は枝番束を結合。
"""
from __future__ import annotations

import os
from collections import Counter

import core as fn_core
import reader as fn_reader
import evidence_source as fn_source

from mcp.server.fastmcp import FastMCP

_INSTRUCTIONS = (
    "号証リネーム（決定論）。号証↔標目の入力は2通り: (a) pasted_text に「号証」「標目」2列を"
    "貼り付け、(b) source_path に証拠説明書ファイル（.xlsx/.csv/.docx）のパスを渡す。"
    "rename_execute が計画を作り、warningsが無ければそのまま mints 正規名へ出力する。"
    "dry_run=true で計画だけ確認（絶対に書き込まない）。warningsが出た場合は内容を確認し、"
    "問題なければ force=true を付けて再度呼び出すと実行する。"
    "範囲表記（甲001-1~2）は枝番束を結合。対象PDFは既にファイル名に号証番号が入っている必要が"
    "ある（stamp_execute の出力等）。原本は不変、出力は隣の「(元フォルダ名)_提出用」へ。"
)

mcp = FastMCP("ltl-rename", instructions=_INSTRUCTIONS)

_STATUS_LABELS = {
    fn_core.STATUS_RENAME: "リネーム", fn_core.STATUS_MERGE: "結合",
    fn_core.STATUS_NO_PDF: "PDFなし", fn_core.STATUS_NOT_IN_TEMPLATE: "対象外",
    fn_core.STATUS_COLLISION: "名前衝突",
}


# LLMが崩しがちなパス表記の吸収用（全角スラッシュ→半角。ドライブ文字脱落は復元不可）
_PATH_FIX = str.maketrans({"／": "/", "＼": "\\"})


def _clean_path(path: str) -> str:
    """小型モデルが渡すパスの表記ゆれを吸収する（原本は読むだけ・書き換えない）。
    前後の空白/全角空白/引用符を除去、file:// を剥がし、全角スラッシュや
    バックスラッシュを半角スラッシュへ寄せる。さらに各パス成分の前後空白を除去
    （小型モデルが「.../user/ Documents/...」のように区切り直後へ挿入する余計な
    空白を救済。成分内部の空白＝「My Documents」等は保持）。
    C: の脱落など情報欠落は復元不可。"""
    s = str(path).translate(_PATH_FIX).strip()
    for q in ('"', "'"):
        if len(s) >= 2 and s[0] == q and s[-1] == q:
            s = s[1:-1].strip()
    low = s.lower()
    if low.startswith("file:///"):
        s = s[8:]
    elif low.startswith("file://"):
        s = s[7:]
    s = s.replace("\\", "/")
    return "/".join(part.strip() for part in s.split("/"))


def _abs(path: str) -> str:
    return os.path.abspath(os.path.expanduser(_clean_path(path)))


def _check_dir(folder: str):
    p = _abs(folder)
    return (p, None) if os.path.isdir(p) else (None, f"フォルダが見つかりません: {p}")


def _plan_to_dict(p) -> dict:
    d = {"status": p.status, "status_label": _STATUS_LABELS.get(p.status, p.status)}
    if p.kosho is not None:
        d["kosho"] = p.kosho.label()
    if p.hyoumoku:
        d["hyoumoku"] = p.hyoumoku
    if p.current_name:
        d["current_name"] = p.current_name
    if p.new_name:
        d["new_name"] = p.new_name
    if p.source_paths:
        d["source_count"] = len(p.source_paths)
    return d


@mcp.tool()
def rename_folder_stats(folder: str) -> dict:
    """フォルダ直下のPDF総数と、号証として認識できたPDF数を返す。rename_plan前の健全性確認。"""
    d, err = _check_dir(folder)
    if err:
        return {"error": err}
    total, recognizable = fn_core.folder_pdf_stats(d)
    return {"folder": d, "total_pdfs": total, "recognizable": recognizable}


@mcp.tool()
def rename_execute(folder: str, pasted_text: str = "", source_path: str = "",
                    dry_run: bool = False, force: bool = False) -> dict:
    """リネーム計画を作り、warnings が無ければそのまま「(元フォルダ名)_提出用」フォルダに
    mints正規名でPDFを出力する（plan/executeを統合）。原本不変。
    号証↔標目の入力は次のどちらか一方（両方指定はエラー）:
      - pasted_text : Excel等で「号証」「標目」2列を選択コピーしたタブ区切り（1行=1号証）。
      - source_path : 証拠説明書ファイル（.xlsx/.csv/.docx）のパス。号証列・標目列を
                      ヘッダから自動検出して読む（LLM経由でも壊れにくい推奨経路）。
    各PDFの新名は mints正規形（甲005 標目.pdf / 乙A001-1 標目.pdf）。
    範囲表記（甲001-1~4）は枝番束の結合。
    dry_run=True は計画だけ返し、絶対に書き込まない（executed=false）。
    warnings（PDFなし/名前衝突）が出た場合、dry_run=False でも force=True を付けない限り
    実行しない（executed=false で計画のみ返す）。"""
    d, err = _check_dir(folder)
    if err:
        return {"error": err}
    has_paste = bool(pasted_text and pasted_text.strip())
    has_source = bool(source_path and source_path.strip())
    if has_paste and has_source:
        return {"error": "pasted_text と source_path はどちらか一方だけ指定してください。"}
    if not has_paste and not has_source:
        return {"error": "号証↔標目の入力がありません（pasted_text か source_path のいずれか）。"}
    if has_source:
        try:
            records = fn_source.read_records(_clean_path(source_path))
        except ValueError as e:
            return {"error": str(e)}
        if not records:
            return {"error": f"証拠説明書から号証を読めませんでした: {source_path}"}
    else:
        records = fn_reader.parse_pasted(pasted_text)
    plans = fn_core.build_plan(d, records)
    warnings = [_plan_to_dict(p) for p in plans if p.status in fn_core.WARN_STATUSES]
    counts = {_STATUS_LABELS.get(s, s): n for s, n in Counter(p.status for p in plans).items()}
    plan_out = [_plan_to_dict(p) for p in plans]
    will_output = sum(1 for p in plans if p.will_output)

    if dry_run or (warnings and not force):
        return {"executed": False, "folder": d, "records_parsed": len(records),
                "counts": counts, "will_output": will_output,
                "warnings": warnings, "plan": plan_out}

    if will_output == 0:
        return {"error": "出力対象が0件です。", "warnings": warnings, "plan": plan_out}

    results, out_dir = fn_core.execute(plans, d)
    return {"executed": True, "output_dir": out_dir,
            "succeeded": sum(1 for _, ok, _ in results if ok),
            "failed": sum(1 for _, ok, _ in results if not ok),
            "results": [{"new_name": p.new_name, "ok": ok, "message": msg} for (p, ok, msg) in results],
            "warnings": warnings}


def run():
    """MCPサーバを stdio で起動する（entry.py --mcp から呼ばれる）。"""
    mcp.run()


if __name__ == "__main__":
    run()
