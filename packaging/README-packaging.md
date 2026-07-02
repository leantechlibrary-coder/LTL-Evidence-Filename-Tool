# MSIX パッケージング手順（証拠ファイル名変換ツール）

GUI と MCP を1つの MSIX に同梱する。`entry.py` を exe にフリーズし、MSIX の
**App Execution Alias** で `ltl-rename.exe` を登録する。これにより：

- スタート/タイルから起動 → 引数なし → **GUI**
- MCPクライアントが `ltl-rename --mcp` を起動 → **MCPサーバ（stdio）**

## 前提（ビルド環境に必要なもの）

| 必要なもの | 入手 |
|---|---|
| Python + PyInstaller | `pip install pyinstaller` |
| Windows SDK（makeappx/signtool） | Visual Studio または SDK 単体インストーラ |
| 署名証明書 | ローカル検証は自己署名 `.pfx`（Subject=マニフェストの Publisher と一致）。**ストア提出時は不要**（Store が再署名） |
| 画像アセット | `packaging/Assets/` に PNG（StoreLogo 50x50 / Square150x150 / Square44x44 / Wide310x150 等） |
| ストア識別子 | Partner Center で予約した Identity `Name` と Publisher ID → `AppxManifest.xml` の `[TODO]` を置換 |

## 手順

1. `AppxManifest.xml` の `[TODO]`（Identity Name / Publisher）を Partner Center の値に置換。
2. `packaging/Assets/` にロゴ PNG を用意。
3. `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` を実行
   → `packaging/out/ltl-rename.msix` が出来る。
4. ローカル検証：`Add-AppxPackage packaging\out\ltl-rename.msix`（自己署名証明書を信頼済みにしておく）。
   - GUI：スタートから「証拠ファイル名変換ツール」を起動。
   - MCP：別プロセスから `ltl-rename --mcp` が stdio で応答するか（下記クライアント設定で）。
5. ストア提出：Partner Center にアップロード（Store が署名。`runFullTrust` は審査対象）。

## ひとつ注意：コンソール subsystem と stdio

`--mcp` は stdin/stdout で会話するため、フリーズは **`--console`** で行う（GUI subsystem だと
stdin/stdout が None になり stdio が通らない場合がある）。一方コンソールだと **GUI 起動時に
コンソール窓が一瞬出る**。これは `entry.py` の `_hide_console()`（実装済み。`sys.frozen` 時のみ
動作し、開発中の素の python 実行では親ターミナルを隠さない）が GUI 分岐で消す。

## rename 固有の注意

- `source_path`（証拠説明書ファイル読み取り）の xlsx 対応で **openpyxl** に依存する
  （`evidence_source.py` 内の遅延import）。PyInstaller が同梱し損ねる場合は
  `build.ps1` のフリーズ行に `--hidden-import openpyxl` を追加する。
- docx 読み取りは標準ライブラリ（zipfile+xml）のみ、csv も標準ライブラリのため追加同梱は不要。

## MCPクライアント設定（インストール後）

```json
{ "mcpServers": { "ltl-rename": { "command": "ltl-rename", "args": ["--mcp"] } } }
```

## ストアより前に「今すぐ」MCPを使う（MSIX不要）

App Execution Alias は MSIX の機能だが、**エージェントを動かすだけなら MSIX は要らない**。
`entry.py` をフリーズした exe（または開発中は素の Python）をフルパスで指すだけでよい：

```json
{ "mcpServers": { "ltl-rename": { "command": "C:\\path\\to\\ltl-rename.exe", "args": ["--mcp"] } } }
```
（開発中は `{ "command": "python", "args": ["C:\\...\\entry.py", "--mcp"] }` でも可。）
ストア配布の段で初めて、安定した短い名前のためにエイリアスへ移行すればよい。
