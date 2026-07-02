"""
入口（パッケージング・エントリ）
================================

引数で GUI / MCP を振り分ける薄い入口。`--mcp` の枝では PyQt を一切 import せず、
ヘッドレスのMCPサーバ（stdio）として起動する（MCPクライアントが起動する形）。
引数なしでは従来どおりGUIを起動する。

  ltl-rename            → GUI（証拠ファイル名変換ツール）
  ltl-rename --mcp      → MCPサーバ（rename_* を stdio で提供）

PyInstaller / MSIX のエントリポイントはこのファイルにする。
"""
import sys


def _hide_console():
    # コンソール subsystem でフリーズした exe の GUI 起動時にコンソール窓を隠す
    #（--mcp は stdio が要るため隠さない）。素の python 実行時は親ターミナルを
    # 巻き添えで隠してしまうため、フリーズ後（sys.frozen）のみ動作させる。
    if not getattr(sys, "frozen", False):
        return
    import ctypes
    h = ctypes.windll.kernel32.GetConsoleWindow()
    if h:
        ctypes.windll.user32.ShowWindow(h, 0)  # SW_HIDE


def main():
    if "--mcp" in sys.argv:
        from mcp_server import run        # → core / reader。PyQt は載らない
        run()
    else:
        _hide_console()
        from app import main as gui_main
        gui_main()                        # ここで初めて PyQt6 が載る


if __name__ == "__main__":
    main()
