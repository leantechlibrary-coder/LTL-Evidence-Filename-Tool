"""
証拠リネームツール — GUI (PyQt6)

① PDFフォルダを選択
② 証拠説明書の「号証」「標目」の2列を選んでコピーし、貼り付け欄に貼る
→ プレビュー（状態を色分け）→ リネーム実行。

任意フォーマットのファイル読み込みは行わない。クリップボード経由なら
Excel / スプレッドシート / Word の表 / CSV を問わずタブ区切りで貼れるため、
形式判定が要らず「貼れば必ず解釈できる」一本道にしている。
おかしい行は貼り付け欄でその場で直せる（プレビューと地続き）。

核ロジックは core.py、貼り付け解釈は reader.py。GUIは薄く保つ。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

import core
import reader

APP_NAME = "LTL 証拠ファイル名変換ツール（無料トライアル版）"
APP_VERSION = "1.0"
GITHUB_URL = "https://github.com/leantechlibrary-coder/LTL-Evidence-Filename-Tool"

# ── トライアル設定 ──────────────────────────────────────────
TRIAL_DAYS = 7
# 有料版のMicrosoft StoreページURL
STORE_URL = "https://apps.microsoft.com/detail/9nr0xcfp1bj1?hl=ja-JP&gl=JP"


class TrialManager:
    """無料トライアルの期限を管理する。

    初回起動日を %APPDATA%/LeanTechLibrary/ に記録し、経過日数を返す。
    アンインストールしても記録は残る（他のLTLツールと別ファイル）。
    """

    def __init__(self):
        appdata = os.environ.get("APPDATA", str(Path.home()))
        self._dir = Path(appdata) / "LeanTechLibrary"
        self._file = self._dir / "trial_evidence_filename.json"

    def _read(self) -> dict:
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict):
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def first_launch_date(self) -> datetime:
        """初回起動日を返す。未記録なら今日を記録して返す。"""
        data = self._read()
        if "first_launch" in data:
            return datetime.fromisoformat(data["first_launch"])
        now = datetime.now()
        data["first_launch"] = now.isoformat()
        self._write(data)
        return now

    def days_remaining(self) -> int:
        """トライアル残り日数を返す（0以下 = 期限切れ）。"""
        first = self.first_launch_date()
        elapsed = (datetime.now() - first).days
        return TRIAL_DAYS - elapsed

    def is_expired(self) -> bool:
        return self.days_remaining() <= 0


class TrialDialog(QDialog):
    """起動時に毎回表示するトライアル情報ダイアログ。

    期限内 : 残り日数＋有料版リンク＋［閉じて続ける］→ accept
    期限切れ: 終了メッセージ＋有料版リンク＋［閉じる］→ accept（呼び出し側で終了）
    ×ボタンで閉じた場合は Rejected（呼び出し側で終了）。
    """

    def __init__(self, days_remaining: int, expired: bool, parent=None):
        super().__init__(parent)
        self.expired = expired
        self.setWindowTitle("無料トライアル版 — 証拠ファイル名変換ツール")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(14)

        title = QLabel("証拠ファイル名変換ツール — 無料トライアル版")
        title.setFont(QFont("Yu Gothic UI", 12, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        if expired:
            msg = QLabel(
                "無料トライアル期間（7日間）が終了しました。\n"
                "ご利用いただきありがとうございました。\n\n"
                "引き続きお使いいただくには、有料版をご購入ください。")
        else:
            msg = QLabel(
                f"無料トライアル：残り {days_remaining} 日\n\n"
                "期間中はすべての機能をお使いいただけます。\n"
                "期間終了後も引き続きお使いいただくには、有料版をご購入ください。")
        msg.setWordWrap(True)
        msg.setFont(QFont("Yu Gothic UI", 10))
        layout.addWidget(msg)

        store_btn = QPushButton("Microsoft Store で有料版を見る")
        store_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(STORE_URL)))
        store_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white;"
            " font-weight: bold; padding: 8px; }"
            "QPushButton:hover { background-color: #45a049; }")
        layout.addWidget(store_btn)

        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("閉じる" if expired else "閉じて続ける")
        close_btn.setFixedWidth(140)
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        close_layout.addStretch()
        layout.addLayout(close_layout)


class TextViewerDialog(QDialog):
    """テキスト全文表示用の子ダイアログ"""

    def __init__(self, parent, title: str, content: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        text_edit.setFont(QFont("Yu Gothic UI", 9))
        text_edit.moveCursor(text_edit.textCursor().MoveOperation.Start)
        layout.addWidget(text_edit)

        close_btn = QPushButton("閉じる")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)


class AboutDialog(QDialog):
    """Aboutダイアログ（操作説明書・README・ライセンス情報へのリンク付き）"""

    README_TEXT = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{APP_NAME}\n"
        "README\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "この度は本ツールをご利用いただき、誠にありがとうございます。\n\n"
        "本ツールは、証拠説明書の「号証」「標目」を貼り付けるだけで、\n"
        "フォルダ内のPDFファイル名をmints提出形式（甲001 標目.pdf 等）に\n"
        "そろえる、訴訟実務向けの専用ツールです。\n\n\n"
        "■ 特徴\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "・証拠説明書の2列を貼り付けるだけ（ファイル形式を問わない）\n"
        "  スプレッドシート／Excel／Wordの表／CSVのいずれからコピーしても、\n"
        "  クリップボード経由のため同じように貼り付けられます。\n\n"
        "・mints提出形式に正規化\n"
        "  甲001、甲002-1、乙A001 等。全角は自動で半角化されます。\n\n"
        "・枝番束の結合\n"
        "  「甲002-1~2」のような範囲表記は、枝番PDFを1ファイルに結合します。\n\n"
        "・元ファイルは変更しません\n"
        "  結果は「（フォルダ名）_提出用」に新規出力されます。\n\n\n"
        "■ 動作環境\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "OS：Windows 10 / 11（64bit）\n\n\n"
        "■ クイックスタート\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "1.「PDFフォルダを選択」で、号証PDFの入ったフォルダを開く\n"
        "2. 証拠説明書の「号証」「標目」の2列を選んでコピーし、貼り付け欄に貼る\n"
        "3. プレビューの色分けを確認する\n"
        "4.「リネーム実行」をクリック\n\n\n"
        "■ よくある質問\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Q. 元のPDFファイルが変更されることはありますか？\n"
        "A. ありません。元フォルダはそのまま残り、別フォルダに出力されます。\n\n"
        "Q. ExcelやWordのファイルを直接読み込めますか？\n"
        "A. ファイル読み込みには対応していません。かわりに、表の2列を\n"
        "   選んでコピーし、貼り付けてください。どの形式から貼っても\n"
        "   同じように動作します。\n\n"
        "Q. パスワード保護されたPDFには対応していますか？\n"
        "A. 対応していません。事前に解除してからご使用ください。\n\n\n"
        "■ ご注意事項\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "・本ツールは現状有姿での提供となります。\n"
        "・重要なファイルは必ずバックアップを取ってからご使用ください。\n\n\n"
        "■ 免責事項\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "本ソフトウェアの使用により生じたいかなる損害についても、\n"
        "開発者は一切の責任を負いかねます。\n\n\n"
        "■ 著作権とライセンス\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "開発・販売：Lean Tech Library\n\n"
        "本ソフトウェアはAGPL-3.0ライセンスの下で配布されています。\n"
        "再配布の際はライセンス条件に従ってください。\n\n"
        "ソースコード：\n"
        f"{GITHUB_URL}\n"
    )

    MANUAL_TEXT = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{APP_NAME} 操作説明書\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "■ 概要\n"
        "  証拠説明書の「号証」「標目」を貼り付けると、フォルダ内のPDFを\n"
        "  mints提出形式のファイル名にそろえます。元ファイルは変更せず、\n"
        "  別フォルダに出力します。\n\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1. 基本操作\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "(1) PDFフォルダを選択\n"
        "  ・「① PDFフォルダを選択」ボタンで、号証PDFの入ったフォルダを開きます。\n"
        "  ・フォルダ内のPDFのファイル名（甲1.pdf 等）から号証を読み取ります。\n\n"
        "(2) 証拠説明書の2列を貼り付け\n"
        "  ・証拠説明書（スプレッドシート／Excel／Word／CSV）で、\n"
        "    「号証」列と「標目」列の2列を選んでコピーします。\n"
        "  ・貼り付け欄に貼り付けます（Ctrl+V）。\n"
        "  ・貼り付け後、おかしい行はその場で直せます。\n\n"
        "(3) プレビューを確認\n"
        "  ・各行の状態が色分けで表示されます（下記）。\n"
        "  ・「→ 新ファイル名」で出力後の名前を確認できます。\n\n"
        "(4) リネーム実行\n"
        "  ・「リネーム実行」ボタンをクリックします。\n"
        "  ・確認後、「（フォルダ名）_提出用」フォルダに出力し、自動で開きます。\n\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "2. 貼り付けの形式\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "・1行＝1号証。区切りはタブ（表の2列コピーで自動的にタブ区切りになります）。\n"
        "・左が号証、右が標目です。\n"
        "・号証の例：甲1 / 甲001 / 甲1の2 / 甲002-1 / 乙A001\n"
        "・全角の英数字は自動的に半角へそろえます（甲００１→甲001）。\n"
        "・種別と番号が別の列に分かれていても読み取ります（「甲」｜「1」）。\n"
        "・見出し行（号証・標目）や空行は自動的に読み飛ばします。\n\n"
        "【枝番束の結合】\n"
        "・「甲002-1~2」のような範囲表記の行は、甲002-1.pdf と 甲002-2.pdf を\n"
        "  1つのPDFに結合し、「甲002-1~2 標目.pdf」として出力します。\n"
        "・束のいずれかが欠けている場合は、結合せず警告（PDFなし）になります。\n\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "3. プレビューの色の意味\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "・色なし（リネーム／結合）：正常に処理されます。\n"
        "・赤（PDFなし）：証拠説明書に行があるのに、対応するPDFがフォルダに\n"
        "  ありません。または枝番束が欠けています。出力されません。\n"
        "・赤（名前衝突）：号証が重複している等、出力名がぶつかります。要確認。\n"
        "・灰（対象外）：フォルダにPDFはあるが、証拠説明書に行がありません。\n"
        "  今回は処理対象外として、そのままにします（正常）。\n\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "4. よくある質問（FAQ）\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Q. 元のファイルが上書きされることはありますか？\n"
        "A. ありません。常に別フォルダに新規ファイルとして出力されます。\n\n"
        "Q. ExcelやWordのファイルを直接開けますか？\n"
        "A. ファイル読み込みには対応していません。表の2列を選んでコピーし、\n"
        "   貼り付けてください。どの形式から貼っても同じように動作します。\n\n"
        "Q. 出力フォルダには何が入りますか？\n"
        "A. リネーム済みPDFと結合済みPDFのみが入ります。提出時の誤アップロードを\n"
        "   防ぐため、PDF以外のファイルは出力しません。処理内容は、元フォルダと\n"
        "   出力フォルダを見比べることで確認できます。\n"
    )

    LICENSE_TEXT = (
        "================================================================================\n"
        "THIRD-PARTY SOFTWARE LICENSES\n"
        f"{APP_NAME}\n"
        "================================================================================\n\n"
        "本ソフトウェアは、以下のオープンソースソフトウェアを使用しています。\n"
        "各ソフトウェアのライセンス条項に従い、ライセンス情報を記載します。\n\n\n"
        "================================================================================\n"
        "1. pypdf\n"
        "================================================================================\n\n"
        "License: BSD-3-Clause License\n"
        "Copyright: Mathieu Fenniak and contributors\n"
        "Website: https://github.com/py-pdf/pypdf\n\n"
        "ライセンス全文：https://github.com/py-pdf/pypdf/blob/main/LICENSE\n\n\n"
        "================================================================================\n"
        "2. PyQt6\n"
        "================================================================================\n\n"
        "License: GNU General Public License v3.0 (GPL-3.0)\n"
        "Copyright: Riverbank Computing Limited\n"
        "Website: https://www.riverbankcomputing.com/software/pyqt/\n\n"
        "ライセンス全文：https://www.gnu.org/licenses/gpl-3.0.txt\n\n\n"
        "================================================================================\n"
        "3. Python\n"
        "================================================================================\n\n"
        "License: Python Software Foundation License (PSF)\n"
        "Copyright: Python Software Foundation\n"
        "Website: https://www.python.org/\n\n"
        "ライセンス全文：https://docs.python.org/3/license.html\n\n\n"
        "================================================================================\n"
        "本ソフトウェアのライセンス\n"
        "================================================================================\n\n"
        f"本ソフトウェア（{APP_NAME}）は、\n"
        "GNU Affero General Public License v3.0 (AGPL-3.0) の下で配布されます。\n"
        "再配布の際はライセンス条件に従ってください。\n\n"
        "ソースコード：\n"
        f"{GITHUB_URL}\n\n\n"
        "================================================================================\n"
        "免責事項\n"
        "================================================================================\n\n"
        "本ソフトウェアは「現状有姿」(AS IS) で提供され、いかなる保証もありません。\n"
        "本ソフトウェアの使用により生じたいかなる損害についても、開発者は\n"
        "一切の責任を負いません。\n"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("このソフトについて")
        self.resize(540, 500)
        self.setMinimumSize(420, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        title_label = QLabel(f"{APP_NAME} v{APP_VERSION}")
        title_label.setFont(QFont("Yu Gothic UI", 12, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        about_text = QTextEdit()
        about_text.setReadOnly(True)
        about_text.setFont(QFont("Yu Gothic UI", 9))
        about_text.setPlainText(
            "【動作環境】\n"
            "Windows 10 / 11 (64bit)\n\n"
            "【概要】\n"
            "証拠説明書の「号証」「標目」を貼り付けると、フォルダ内のPDFを\n"
            "mints提出形式のファイル名にそろえます。元ファイルは変更しません。\n\n"
            "【免責事項】\n"
            "本ソフトウェアは「現状有姿」(AS IS) で提供されます。\n\n"
            "■ 無保証・現状有姿の提供\n"
            "正確性・継続的動作その他、明示・黙示を問わずいかなる保証も\n"
            "行いません。\n\n"
            "■ 免責\n"
            "本ソフトウェアの使用または使用不能から生じるいかなる損害\n"
            "（出力ファイル名の誤り、ファイルの消失、業務上の損失等を含む）\n"
            "についても、開発者は一切の責任を負いません。\n\n"
            "■ 利用者の責任\n"
            "出力結果の確認、バックアップの取得、業務上の判断は、すべて\n"
            "利用者の責任において行ってください。本ソフトウェアは法律実務の\n"
            "補助を目的とするものであり、法律相談・法的判断の提供ではありません。\n\n"
            "■ サポート\n"
            "動作保証・バグ修正・機能追加・質問対応等のサポートの提供は\n"
            "予定していません。\n\n"
            "■ データの取り扱い\n"
            "すべての処理はお使いのPC内で完結し、ファイルやデータが外部へ\n"
            "送信されることはありません。\n\n"
            "【開発・販売】\n"
            "Lean Tech Library\n\n"
            "ご使用前に操作説明書・READMEをご確認ください。"
        )
        layout.addWidget(about_text)

        link_layout = QHBoxLayout()
        link_layout.setSpacing(8)
        manual_btn = QPushButton("操作説明書")
        manual_btn.clicked.connect(self._show_manual)
        readme_btn = QPushButton("README")
        readme_btn.clicked.connect(self._show_readme)
        license_btn = QPushButton("ライセンス情報")
        license_btn.clicked.connect(self._show_licenses)
        link_layout.addWidget(manual_btn)
        link_layout.addWidget(readme_btn)
        link_layout.addWidget(license_btn)
        layout.addLayout(link_layout)

        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_btn = QPushButton("閉じる")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        close_layout.addWidget(close_btn)
        close_layout.addStretch()
        layout.addLayout(close_layout)

    def _show_manual(self):
        TextViewerDialog(self, "操作説明書", self.MANUAL_TEXT).exec()

    def _show_readme(self):
        TextViewerDialog(self, "README", self.README_TEXT).exec()

    def _show_licenses(self):
        TextViewerDialog(self, "ライセンス情報", self.LICENSE_TEXT).exec()


def show_about_dialog():
    AboutDialog().exec()

STATUS_LABEL = {
    core.STATUS_RENAME: "リネーム",
    core.STATUS_MERGE: "結合",
    core.STATUS_NO_PDF: "PDFなし",
    core.STATUS_NOT_IN_TEMPLATE: "対象外",
    core.STATUS_COLLISION: "名前衝突",
}

# 行の背景色（3トーン）
STATUS_COLOR = {
    core.STATUS_RENAME: None,                            # 通常（色なし）
    core.STATUS_MERGE: None,                             # 通常（色なし）
    core.STATUS_NO_PDF: QColor(255, 221, 221),           # 赤: 説明書に行があるのにPDFが無い
    core.STATUS_COLLISION: QColor(255, 221, 221),        # 赤: 号証重複・名前衝突（要確認）
    core.STATUS_NOT_IN_TEMPLATE: QColor(238, 238, 238),  # 灰: 今回対象外（正常）
}

PLACEHOLDER = (
    "ここに証拠説明書の「号証」「標目」の2列を貼り付け\n"
    "（例）\n"
    "甲1\t賃貸借契約書\n"
    "甲1の2\t重要事項説明書\n"
    "甲2\t解除通知書\n"
    "甲3-1~2\t写真"
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 640)

        self.folder = None
        self.plans = []

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # ① フォルダ（②と同じ黄色の囲いの中にボタンと対応ファイル名の説明）
        top = QHBoxLayout()
        step1_box = QFrame()
        step1_box.setObjectName("step1box")
        step1_box.setStyleSheet(
            "QFrame#step1box {"
            " background-color: #FFF9C4; border: 1px solid #FBC02D; }")
        step1_layout = QHBoxLayout(step1_box)
        step1_layout.setContentsMargins(10, 8, 10, 8)
        step1_layout.setSpacing(10)
        self.btn_folder = QPushButton("① PDFフォルダを選択")
        self.btn_folder.clicked.connect(self.choose_folder)
        step1_layout.addWidget(self.btn_folder)
        lbl_step1_note = QLabel(
            "証拠番号付与ツールで番号を付けたPDF（例：甲001.pdf）を認識します。\n"
            "枝番ファイル（例：甲001-1・甲001-2）は、証拠説明書の記載が"
            "「甲001-1~2」のとき単一ファイル（例：甲001-1~2.pdf）に結合します。")
        lbl_step1_note.setWordWrap(True)
        lbl_step1_note.setStyleSheet(
            "font-size: 9pt; color: #555; background: transparent; border: none;")
        step1_layout.addWidget(lbl_step1_note, stretch=1)
        top.addWidget(step1_box, stretch=1)

        about_label = QLabel('<a href="#" style="color: #888;">About</a>')
        about_label.setOpenExternalLinks(False)
        about_label.linkActivated.connect(lambda: show_about_dialog())
        top.addWidget(about_label)
        root.addLayout(top)
        self.lbl_paths = QLabel("フォルダ: 未選択")
        self.lbl_paths.setWordWrap(True)
        self.lbl_paths.setContentsMargins(40, 0, 0, 0)  # 開始位置を約5文字分右へ
        root.addWidget(self.lbl_paths)
        self.lbl_folder_warn = QLabel("")
        self.lbl_folder_warn.setWordWrap(True)
        self.lbl_folder_warn.setContentsMargins(40, 0, 0, 0)
        self.lbl_folder_warn.setStyleSheet("color: #C62828; font-size: 9pt;")
        self.lbl_folder_warn.hide()
        root.addWidget(self.lbl_folder_warn)

        # ② 貼り付け欄（指示文は黄色で囲む）
        lbl_step2 = QLabel(
            "② 証拠説明書の「号証」「標目」の2列を選んでコピーし、下に貼り付け"
            "（貼付後にテキストは修正可）")
        lbl_step2.setWordWrap(True)
        lbl_step2.setStyleSheet(
            "QLabel {"
            " background-color: #FFF9C4; border: 1px solid #FBC02D;"
            " padding: 10px; font-size: 10pt; }")
        root.addWidget(lbl_step2)
        self.txt = QPlainTextEdit()
        self.txt.setPlaceholderText(PLACEHOLDER)
        self.txt.setFont(QFont("Consolas", 10))
        self.txt.setMaximumHeight(160)
        self.txt.textChanged.connect(self.refresh_preview)
        root.addWidget(self.txt)

        # プレビュー表
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["号証", "標目", "現在のファイル名", "→ 新ファイル名", "状態"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)

        self.lbl_summary = QLabel("")
        root.addWidget(self.lbl_summary)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.btn_run = QPushButton("リネーム実行")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self.run_rename)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 12pt;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover:enabled {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #C8C8C8;
                color: #F0F0F0;
            }
        """)
        bottom.addWidget(self.btn_run)
        root.addLayout(bottom)

    # ---- フォルダ ----
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "PDFフォルダを選択")
        if d:
            self.folder = d
            self.lbl_paths.setText(f"フォルダ: {self.folder}")
            self._check_folder()
            self.refresh_preview()

    def _check_folder(self):
        """フォルダ選択直後の事前チェック。号証として読めるPDFが無ければ知らせる。"""
        if not self.folder:
            self.lbl_folder_warn.hide()
            return
        total, recognizable = core.folder_pdf_stats(self.folder)
        if total == 0:
            self.lbl_folder_warn.setText(
                "※ このフォルダにPDFが見つかりません。フォルダの選び間違いか、"
                "PDFがサブフォルダの中にある可能性があります。")
            self.lbl_folder_warn.show()
        elif recognizable == 0:
            self.lbl_folder_warn.setText(
                f"※ このフォルダのPDF（{total}件）はいずれも号証として読めません。"
                "まだ号証を付与していない場合は、先に「証拠番号付与ツール」で"
                "番号を付けてください。")
            self.lbl_folder_warn.show()
        else:
            self.lbl_folder_warn.hide()

    # ---- プレビュー ----
    def refresh_preview(self):
        self.plans = []
        records = reader.parse_pasted(self.txt.toPlainText())
        if not (self.folder and records):
            self.table.setRowCount(0)
            self.lbl_summary.setText(
                "フォルダと貼り付けの両方がそろうとプレビューします。"
                if self.txt.toPlainText().strip() or self.folder else "")
            self.btn_run.setEnabled(False)
            return
        self.plans = core.build_plan(self.folder, records)
        self.fill_table()

    def fill_table(self):
        self.table.setRowCount(len(self.plans))
        n_out = n_warn = 0
        for r, p in enumerate(self.plans):
            if p.kosho:
                kosho = p.kosho.label()
            elif p.status == core.STATUS_MERGE and p.new_name:
                kosho = os.path.splitext(p.new_name)[0].split(" ")[0]  # 範囲（甲001-1~2）
            else:
                kosho = ""
            cells = [kosho, p.hyoumoku or "", p.current_name or "", p.new_name or "",
                     STATUS_LABEL.get(p.status, p.status)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                color = STATUS_COLOR.get(p.status)
                if color:
                    item.setBackground(color)
                self.table.setItem(r, c, item)
            if p.will_output:
                n_out += 1
            elif p.status in (core.STATUS_NO_PDF, core.STATUS_COLLISION):
                n_warn += 1
        self.lbl_summary.setText(f"処理対象 {n_out} 件（リネーム＋結合） ／ 警告 {n_warn} 件")
        self.btn_run.setEnabled(n_out > 0)

    # ---- 実行 ----
    def run_rename(self):
        n = sum(1 for p in self.plans if p.will_output)
        ok = QMessageBox.question(
            self, "確認",
            f"{n} 件の提出物を作成します。\n"
            "元のフォルダはそのまま残り、「（フォルダ名）_提出用」に\n"
            "リネーム済みファイルと結合したファイルを書き出します。\n続行しますか？")
        if ok != QMessageBox.StandardButton.Yes:
            return
        results, out_dir = core.execute(self.plans, self.folder)
        failed = [(p, msg) for p, succeeded, msg in results if not succeeded]
        if failed:
            detail = "\n".join(f"{p.current_name}: {msg}" for p, msg in failed)
            QMessageBox.warning(self, "一部失敗",
                                f"{len(failed)} 件失敗しました。\n出力先: {out_dir}\n{detail}")
        else:
            QMessageBox.information(
                self, "完了",
                f"{len(results)} 件を書き出しました。\n出力先: {out_dir}")
        try:
            if sys.platform == "win32":
                os.startfile(out_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{out_dir}"')
            else:
                os.system(f'xdg-open "{out_dir}"')
        except Exception:
            pass
        self.refresh_preview()


def main():
    app = QApplication(sys.argv)

    # --- トライアルチェック ---
    trial = TrialManager()
    remaining = trial.days_remaining()
    expired = trial.is_expired()

    dlg = TrialDialog(remaining, expired)
    if expired:
        # 期限切れ → ダイアログを見せてから終了
        dlg.exec()
        sys.exit(0)
    else:
        # 期限内 → ［閉じて続ける］でメインへ。×で閉じたら終了。
        if dlg.exec() == QDialog.DialogCode.Rejected:
            sys.exit(0)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
