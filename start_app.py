#!/usr/bin/env python3
import subprocess
import sys
import os
import time
import logging
import webbrowser
import venv # 仮想環境作成用

# プロジェクトのルートディレクトリを取得 (スクリプトがあるディレクトリ)
project_root = os.path.dirname(os.path.abspath(__file__))
# sys.path.insert(0, project_root) # uvicorn サブプロセスには引き継がれないため削除

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --- 設定 ---
# FastAPI アプリケーションのモジュールとFastAPIインスタンス名
APP_MODULE = "src.web_app:app"
# FastAPI がリッスンするホストとポート
HOST = "127.0.0.1"
PORT = 8000
# アプリケーションのURL
APP_URL = f"http://{HOST}:{PORT}"
# 仮想環境のディレクトリ名
VENV_DIR = "venv"
# requirements.txt ファイルのパス
REQUIREMENTS_FILE = "requirements.txt"

# --- ヘルパー関数 ---
def create_virtual_environment(venv_dir):
    """仮想環境を作成する"""
    logger.info(f"仮想環境 '{venv_dir}' を作成します...")
    try:
        venv.create(venv_dir, with_pip=True)
        logger.info(f"仮想環境 '{venv_dir}' の作成が完了しました。")
        return True
    except Exception as e:
        logger.error(f"仮想環境の作成に失敗しました: {e}")
        return False

def get_python_executable(venv_dir):
    """仮想環境内のPython実行可能ファイルのパスを取得する"""
    if sys.platform.startswith('win'):
        # Windows
        return os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        # macOS, Linux
        return os.path.join(venv_dir, "bin", "python")

def get_virtual_environment_site_packages(venv_dir):
    """仮想環境の site-packages ディレクトリのパスを取得する"""
    if sys.platform.startswith('win'):
        # Windows
        return os.path.join(venv_dir, "Lib", "site-packages")
    else:
        # macOS, Linux (Pythonのバージョンによってパスが異なる場合がある)
        # 例: venv/lib/python3.9/site-packages
        # 仮想環境内のpython実行ファイルを使って site-packages のパスを取得するのが確実
        python_executable = get_python_executable(venv_dir)
        try:
            result = subprocess.run(
                [python_executable, "-c", "import site; print(site.getsitepackages()[0])"],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"仮想環境の site-packages パスの取得に失敗しました: {e}")
            # 失敗した場合は一般的なパスを返すか、Noneを返すか検討
            # ここでは一般的なパスを試す
            python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
            return os.path.join(venv_dir, "lib", python_version, "site-packages")


def install_requirements(python_executable, requirements_file):
    """指定されたPython環境で requirements.txt に基づいて依存関係をインストール"""
    logger.info(f"依存関係をインストールします ({requirements_file})...")
    if not os.path.exists(requirements_file):
        logger.error(f"'{requirements_file}' が見つかりません。")
        return False
    try:
        subprocess.run([python_executable, "-m", "pip", "install", "-r", requirements_file], check=True)
        logger.info("依存関係のインストールが完了しました。")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"依存関係のインストールに失敗しました: {e}")
        return False
    except Exception as e:
        logger.error(f"依存関係インストール中に予期せぬエラー: {e}")
        return False


def check_uvicorn_installed(python_executable):
    """指定されたPython環境に uvicorn がインストールされているかチェック"""
    try:
        subprocess.run([python_executable, "-m", "uvicorn", "--version"], check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def is_process_running(process_name):
    """指定された名前のプロセスが実行中かチェック (簡易版)"""
    current_pid = os.getpid() # 現在のプロセスのPIDを取得
    try:
        if sys.platform.startswith('win'):
            # Windows (tasklist /v を使用してコマンドラインを取得)
            result = subprocess.run(['tasklist', '/v', '/fo', 'csv'], capture_output=True, text=True, check=True)
            lines = result.stdout.splitlines()
            # ヘッダー行をスキップ
            if len(lines) > 0:
                 lines = lines[1:]

            for line in lines:
                 # CSV形式を解析 (手抜き)
                 parts = line.strip().split('","')
                 if len(parts) > 8: # 想定される列数より多いか確認
                      image_name = parts[0].strip('"')
                      pid_str = parts[1].strip('"')
                      command_line = parts[8].strip('"') # コマンドラインは通常9番目の要素

                      try:
                           pid = int(pid_str)
                           # プロセス名に uvicorn が含まれ、かつコマンドラインに APP_MODULE が含まれ、かつ現在のプロセスでない
                           if process_name in image_name.lower() and APP_MODULE in command_line and pid != current_pid:
                                logging.debug(f"実行中のプロセスを検出 (Windows): PID={pid}, Image='{image_name}', Cmd='{command_line}'")
                                return True
                      except (ValueError, IndexError):
                           pass # PIDの解析に失敗した場合

            return False
        else:
            # macOS, Linux (ps aux を使用してコマンドラインを取得)
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                 # PIDは通常2番目の要素、コマンドラインはその後
                 parts = line.split(maxsplit=10) # コマンドライン部分をまとめて取得
                 if len(parts) > 10: # 想定される列数より多いか確認
                      pid_str = parts[1]
                      command_line = parts[10] # コマンドラインは通常11番目の要素 (インデックス10)

                      try:
                           pid = int(pid_str)
                           # コマンドラインに uvicorn と APP_MODULE の両方が含まれ、かつ現在のプロセスでない
                           if process_name in command_line and APP_MODULE in command_line and pid != current_pid:
                                logging.debug(f"実行中のプロセスを検出 (Unix): PID={pid}, Cmd='{command_line}'")
                                return True
                      except (ValueError, IndexError):
                           pass # PIDの解析に失敗した場合
            return False
    except Exception as e:
        logging.error(f"プロセス実行中チェック中にエラーが発生しました: {e}", exc_info=True)
        return False # エラー発生時は実行中ではないと判断


# --- メイン処理 ---
def main():
    logger.info("アプリケーション起動スクリプトを開始します。")

    # プロジェクトのルートディレクトリを取得 (スクリプトがあるディレクトリ)
    # project_root は既にスクリプトの先頭で取得済み
    os.chdir(project_root) # プロジェクトルートに移動

    # 仮想環境のパス
    venv_path = os.path.join(project_root, VENV_DIR)
    python_executable = get_python_executable(venv_path)

    # 仮想環境が存在しない場合は作成
    if not os.path.exists(venv_path):
        if not create_virtual_environment(venv_path):
            logger.error("仮想環境の作成に失敗したため、終了します。")
            sys.exit(1)

    # 仮想環境内のPython実行可能ファイルが存在するか確認
    if not os.path.exists(python_executable):
         logger.error(f"仮想環境内にPython実行可能ファイルが見つかりません: {python_executable}")
         logger.error("仮想環境の作成に失敗した可能性があります。手動で仮想環境を作成してみてください。")
         sys.exit(1)


    # 仮想環境内に依存関係がインストールされているかチェック
    if not check_uvicorn_installed(python_executable):
         logger.warning("仮想環境に依存関係がインストールされていません。インストールします。")
         if not install_requirements(python_executable, REQUIREMENTS_FILE):
              logger.error("依存関係のインストールに失敗したため、終了します。")
              sys.exit(1)
         # インストール後、再度チェック
         if not check_uvicorn_installed(python_executable):
              logger.error("仮想環境への依存関係のインストールを確認できませんでした。手動で仮想環境をアクティベートし、'pip install -r requirements.txt' を実行してください。")
              sys.exit(1)


    # バックエンドが既に実行中かチェック (簡易版)
    # uvicorn プロセス名をチェック
    if is_process_running("uvicorn"):
        logger.warning(f"バックエンドプロセス (uvicorn) が既に実行中のようです。URL: {APP_URL} を開きます。")
        webbrowser.open(APP_URL)
        sys.exit(0)


    logger.info(f"バックエンドサーバーを仮想環境で起動します: {APP_MODULE} on {HOST}:{PORT}")
    # バックエンドサーバーを仮想環境内のPythonで起動
    # PYTHONPATH を設定して プロジェクトルート と 仮想環境のsite-packages をモジュール検索パスに追加
    current_env = os.environ.copy()
    venv_site_packages = get_virtual_environment_site_packages(venv_path)
    if venv_site_packages and os.path.exists(venv_site_packages):
         # 既存の PYTHONPATH にプロジェクトルートと仮想環境の site-packages を追加
         current_env['PYTHONPATH'] = project_root + os.pathsep + venv_site_packages + os.pathsep + current_env.get('PYTHONPATH', '')
         logger.debug(f"PYTHONPATH を設定 (プロジェクトルート + venv site-packages): {current_env['PYTHONPATH']}")
    else:
         # site-packages が見つからない場合はプロジェクトルートのみ追加 (以前の挙動)
         current_env['PYTHONPATH'] = project_root + os.pathsep + current_env.get('PYTHONPATH', '')
         logger.warning(f"仮想環境の site-packages が見つかりませんでした。PYTHONPATH にプロジェクトルートのみ追加: {current_env['PYTHONPATH']}")


    # --reload オプションは開発中に便利ですが、本番環境では注意が必要です。
    # ここでは開発環境を想定し、ホットリロードを有効にします。
    try:
        backend_process = subprocess.Popen(
            [python_executable, "-m", "uvicorn", APP_MODULE, "--host", HOST, "--port", str(PORT), "--reload"],
            cwd=project_root, # プロジェクトルートをカレントディレクトリとして指定
            env=current_env # PYTHONPATH を設定した環境変数を渡す
        )
        logger.info(f"バックエンドプロセスを起動しました (PID: {backend_process.pid})")

        # サーバーが起動するまで少し待機
        logger.info("サーバー起動を待機中...")
        time.sleep(5) # サーバー起動に必要な時間に応じて調整 (以前より少し長く)

        # ブラウザでフロントエンドを開く
        logger.info(f"ブラウザでアプリケーションを開きます: {APP_URL}")
        webbrowser.open(APP_URL)

        # バックエンドプロセスが終了するのを待つ
        backend_process.wait()

    except FileNotFoundError:
        logger.error(f"Python実行可能ファイルまたはuvicornが見つかりません。仮想環境が正しく作成され、依存関係がインストールされているか確認してください。")
        sys.exit(1)
    except Exception as e:
        logger.error(f"アプリケーション起動中にエラーが発生しました: {e}", exc_info=True)
        sys.exit(1)

    logger.info("アプリケーション起動スクリプトが終了しました。")

if __name__ == "__main__":
    main()