# 証拠ファイル名変換ツール — MSIX ビルド（雛形）
# 前提（このスクリプトを動かす環境に必要なもの）:
#   - Python + PyInstaller   : pip install pyinstaller
#   - Windows SDK            : makeappx.exe / signtool.exe（Visual Studio または SDK 単体）
#   - 署名証明書             : ローカル検証は自己署名 .pfx。ストア提出時は Store が再署名
#   - 画像アセット           : packaging\Assets\*.png（StoreLogo/Square150/Square44/Wide310）
#
# 使い方:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$App   = "ltl-rename"
$Pkg   = Split-Path -Parent $MyInvocation.MyCommand.Path   # packaging\
$Root  = Split-Path -Parent $Pkg                            # リポジトリ直下
$Stage = Join-Path $Pkg "stage"
$Out   = Join-Path $Pkg "out"

function Find-SdkTool($name) {
  $p = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\$name" -ErrorAction SilentlyContinue |
       Select-Object -Last 1 -Expand FullName
  if (-not $p) { throw "$name が見つかりません（Windows SDK を入れてください）" }
  return $p
}

# 1) entry.py を exe にフリーズ
#    --console: --mcp の stdio を確実に通すためコンソール subsystem。
#    （GUI起動時のコンソール非表示は entry.py 側で対応する想定。README 参照）
#    ※ source_path の xlsx 読みで openpyxl を使う（evidence_source 内の遅延import）。
#      PyInstaller が拾い損ねる場合は --hidden-import openpyxl を追加する。
& python -m PyInstaller --noconfirm --console --name $App (Join-Path $Root "entry.py")

# 2) MSIX レイアウトを stage に組む（exe一式 + マニフェスト + アセット）
Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "dist\$App") $Stage -Recurse
Copy-Item (Join-Path $Pkg "AppxManifest.xml") (Join-Path $Stage "AppxManifest.xml")
Copy-Item (Join-Path $Pkg "Assets") (Join-Path $Stage "Assets") -Recurse

# 3) パッケージ化
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$makeappx = Find-SdkTool "makeappx.exe"
& $makeappx pack /d $Stage /p (Join-Path $Out "$App.msix") /o

# 4) 署名（ローカル検証用。ストア提出時は不要＝Storeが再署名）
#    自己署名証明書の Subject は AppxManifest の Publisher と完全一致が必須。
$pfx = Join-Path $Pkg "test-cert.pfx"
if (Test-Path $pfx) {
  $signtool = Find-SdkTool "signtool.exe"
  & $signtool sign /fd SHA256 /a /f $pfx /p "PASSWORD" (Join-Path $Out "$App.msix")
  Write-Host "署名済み: $Out\$App.msix（ローカルで Add-AppxPackage で検証可）"
} else {
  Write-Host "未署名: $Out\$App.msix（test-cert.pfx を置くとローカル検証用に署名します）"
}
