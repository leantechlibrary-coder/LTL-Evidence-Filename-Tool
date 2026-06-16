# LTL 証拠ファイル名変換ツール

mints（民事裁判書類電子提出システム）への証拠提出用に、証拠PDFのファイル名を mints の正規形へ一括変換するWindowsデスクトップツールです。

## 概要

証拠番号付与ツールで出力したPDF（`甲001.pdf` 等）のファイル名を、証拠説明書の標目を付けて `甲001 契約書.pdf` の形にリネームします。対象のPDFファイルを選択し、証拠説明書の番号と標目を貼り付けて実行するだけで、ファイル名が mints の正規形（種別＋半角3桁＋半角スペース＋標目）に一括で変換されます。

枝番は、証拠説明書に `甲002-1~2` と記載されていれば、`甲002-1.pdf` と `甲002-2.pdf` を一つのPDFに結合し、`甲002-1~2 賃貸借契約書.pdf` として出力します。

すべての処理はローカル環境（お使いのパソコン内）で完結し、ファイルおよびファイル名が外部に送信されることはありません。

## 動作環境

- Windows 11（64bit）

## インストール

Microsoft Store から入手してください。

URL：

## ライセンス

本ソフトウェアは GNU Affero General Public License v3.0（AGPL-3.0）の下で配布されます。

ソースコード：https://github.com/leantechlibrary-coder/LTL-Evidence-Filename-Tool

## サードパーティライセンス

本ソフトウェアは以下のライブラリを使用しています。

- pypdf — BSD License（BSD-3-Clause） — https://github.com/py-pdf/pypdf
- PyQt6 — GPL-3.0
- Python および標準ライブラリ — Python Software Foundation License（PSF）

各ライブラリのライセンス全文は、それぞれの配布元を参照してください。

## 免責事項

本ソフトウェアは「現状有姿」（AS IS）で提供され、いかなる保証もありません。本ソフトウェアの使用により生じたいかなる損害についても、開発者は一切の責任を負いません。

## 開発・販売

Lean Tech Library
