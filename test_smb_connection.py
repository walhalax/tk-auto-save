import sys
import logging
import os
from dotenv import load_dotenv

# ロギング設定 (念のため残しておくが、printで主要な出力を確認)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

try:
    from smb.SMBConnection import SMBConnection
    from smb import smb_structs
    from smb.base import OperationFailure
    print("Successfully imported pysmb.") # print で出力
except ImportError as e:
    print(f"Error: Failed to import pysmb: {e}") # print で出力
    print(f"Python executable: {sys.executable}") # print で出力
    print(f"sys.path: {sys.path}") # print で出力
    sys.exit("Error: pysmb library not found. Please install it using 'pip install pysmb'.")

# .envファイルから環境変数を読み込む
load_dotenv()

# --- サーバー設定 (環境変数から取得) ---
FILEHUB_ADDRESS = os.getenv("FILEHUB_ADDRESS")
FILEHUB_SHARE = os.getenv("FILEHUB_SHARE")
FILEHUB_BASE_PATH = os.getenv("FILEHUB_BASE_PATH", "/").lstrip('/') # 共有内のベースパス, 先頭の / を削除
FILEHUB_USER = os.getenv("FILEHUB_USER")
FILEHUB_PASSWORD = os.getenv("FILEHUB_PASSWORD")
MY_NAME = os.getenv("SMB_MY_NAME", "local_machine") # 接続元クライアント名 (任意)
REMOTE_NAME = os.getenv("SMB_REMOTE_NAME", FILEHUB_ADDRESS) # 接続先サーバー名

def test_smb_connection():
    """SMBサーバーへの接続と共有フォルダのリスト表示をテストする"""
    print("SMB接続テストを開始します。") # print で出力

    if not FILEHUB_ADDRESS or not FILEHUB_SHARE or not FILEHUB_USER or not FILEHUB_PASSWORD:
        print("Error: SMB接続に必要な環境変数 (FILEHUB_ADDRESS, FILEHUB_SHARE, FILEHUB_USER, FILEHUB_PASSWORD) が設定されていません。.env ファイルを確認してください。") # print で出力
        return False

    conn = None
    try:
        print(f"Attempting to connect to SMB server at {FILEHUB_ADDRESS}:445") # print で出力
        smb_structs.SUPPORT_SMB2 = True # SMB2/3 を優先的に試す
        conn = SMBConnection(FILEHUB_USER, FILEHUB_PASSWORD, MY_NAME, REMOTE_NAME, use_ntlm_v2=True)

        # 接続タイムアウトを短めに設定することも検討可能 (例: timeout=5)
        connected = conn.connect(FILEHUB_ADDRESS, 445)
        if not connected:
             print(f"Error: SMBサーバーへの接続に失敗しました: {FILEHUB_ADDRESS}:445") # print で出力
             return False

        print(f"Successfully connected to SMB server at {FILEHUB_ADDRESS}") # print で出力

        # 共有フォルダのルートパスをリスト
        list_path = FILEHUB_BASE_PATH if FILEHUB_BASE_PATH else '/' # ベースパスが空の場合はルートをリスト
        print(f"Listing contents of shared folder '{FILEHUB_SHARE}' at path '{list_path}'") # print で出力

        shared_files = conn.listPath(FILEHUB_SHARE, list_path)

        print(f"Contents of path '{list_path}':") # print で出力
        if not shared_files:
            print("  (Empty)") # print で出力
        else:
            for shared_file in shared_files:
                file_type = "Dir" if shared_file.isDirectory else "File"
                print(f"  [{file_type}] {shared_file.filename}") # print で出力

        print("SMB接続テストが完了しました。") # print で出力
        return True

    except OperationFailure as e:
        print(f"Error: SMB操作エラーが発生しました: {e}") # print で出力
        print(f"Error Code: {e.message}") # print で出力
        return False
    except Exception as e:
        print(f"Error: SMB接続テスト中に予期せぬエラーが発生しました: {e}") # print で出力
        return False
    finally:
        if conn:
            print("Closing SMB connection.") # print で出力
            conn.close()
            print("SMB connection closed.") # print で出力

if __name__ == "__main__":
    if test_smb_connection():
        print("SMB connection test succeeded.") # print で出力
        sys.exit(0)
    else:
        print("SMB connection test failed.") # print で出力
        sys.exit(1)