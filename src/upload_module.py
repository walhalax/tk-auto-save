import sys
import logging
try:
    # import pysmbclient # 旧ライブラリ
    from smb.SMBConnection import SMBConnection
    from smb import smb_structs
    from smb.base import OperationFailure # pysmb の例外クラス
    logging.info("Successfully imported pysmb.")
except ImportError as e:
    logging.error(f"Failed to import pysmb: {e}", exc_info=True)
    logging.error(f"Python executable: {sys.executable}")
    logging.error(f"sys.path: {sys.path}")
    raise # 例外を再発生させてアプリケーションを停止させる
import os
import asyncio
import re
from typing import Callable, Dict, Any, Optional
from io import BytesIO # ファイルアップロード用
from dotenv import load_dotenv # .env ファイル読み込み用
import time # 進捗報告のタイミング制御用

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# .envファイルから環境変数を読み込む
load_dotenv()

# --- サーバー設定 (環境変数から取得) ---
FILEHUB_ADDRESS = os.getenv("FILEHUB_ADDRESS", "filehub") # サーバーアドレス or IP
FILEHUB_SHARE = os.getenv("FILEHUB_SHARE", "UsbDisk1_Volume1") # 共有名
FILEHUB_BASE_PATH = os.getenv("FILEHUB_BASE_PATH", "/Adult") # 共有内のベースパス
FILEHUB_USER = os.getenv("FILEHUB_USER")
FILEHUB_PASSWORD = os.getenv("FILEHUB_PASSWORD")
MY_NAME = os.getenv("SMB_MY_NAME", "local_machine") # 接続元クライアント名 (任意)
REMOTE_NAME = os.getenv("SMB_REMOTE_NAME", FILEHUB_ADDRESS) # 接続先サーバー名

# SMBパス形式に変換 (pysmb は / 区切りを推奨)
smb_base_path_pysmb = FILEHUB_BASE_PATH # 例: /Adult

# --- ヘルパー関数 ---
def extract_fc2_prefix(title: str) -> Optional[str]:
    """動画タイトルから FC2-PPV-XXX (3桁) のプレフィックスを抽出"""
    match = re.search(r'FC2-PPV-(\d{3})', title)
    return match.group(0) if match else None

def extract_fc2_full_id(title: str) -> Optional[str]:
    """動画タイトルから FC2-PPV-XXXXXXX (7桁) の完全IDを抽出"""
    match = re.search(r'FC2-PPV-(\d{7})', title)
    return match.group(0) if match else None

# --- SMB 操作関数 (同期) ---
# pysmb を使用するように修正

def _get_smb_connection() -> SMBConnection:
    """SMB接続オブジェクトを作成して返す"""
    if not FILEHUB_USER or not FILEHUB_PASSWORD:
        raise ValueError("SMB認証情報 (ユーザー名またはパスワード) が設定されていません。")
    # use_ntlm_v2=True は多くの環境で推奨される
    smb_structs.SUPPORT_SMB2 = True # SMB2/3 を優先的に試す
    conn = SMBConnection(FILEHUB_USER, FILEHUB_PASSWORD, MY_NAME, REMOTE_NAME, use_ntlm_v2=True)
    return conn

def _check_or_create_smb_directory(target_dir_pysmb: str):
    """SMBサーバー上のディレクトリが存在するか確認し、なければ作成する (同期)"""
    conn = None
    try:
        conn = _get_smb_connection()
        assert conn.connect(FILEHUB_ADDRESS, 139) # ポート139 (NetBIOS) または 445 (Direct Hosting)
        logging.info(f"SMB接続成功: {FILEHUB_ADDRESS}")

        # ディレクトリパス (共有名からの相対パス)
        # 例: /Adult/FC2-PPV-123
        full_path = target_dir_pysmb

        logging.info(f"SMBディレクトリを確認/作成中: {FILEHUB_SHARE}{full_path}")

        try:
            # listPath でディレクトリの存在確認 (ファイル/フォルダ一覧を取得)
            conn.listPath(FILEHUB_SHARE, full_path)
            logging.info(f"ディレクトリは既に存在します: {FILEHUB_SHARE}{full_path}")
        except OperationFailure as e:
            # エラーコードで「存在しない」を判断 (NT STATUS_OBJECT_NAME_NOT_FOUND など)
            # pysmb のエラーコードは複雑な場合があるため、ここでは存在しないと仮定して作成を試みる
            logging.info(f"ディレクトリが存在しないようです。作成を試みます: {FILEHUB_SHARE}{full_path} (Error: {e})")
            try:
                conn.createDirectory(FILEHUB_SHARE, full_path)
                logging.info(f"ディレクトリを作成しました: {FILEHUB_SHARE}{full_path}")
            except OperationFailure as mkdir_e:
                logging.error(f"SMBディレクトリの作成に失敗しました: {FILEHUB_SHARE}{full_path} - {mkdir_e}", exc_info=True)
                raise
            except Exception as mkdir_e_gen:
                 logging.error(f"SMBディレクトリ作成中に予期せぬエラー: {FILEHUB_SHARE}{full_path} - {mkdir_e_gen}", exc_info=True)
                 raise
        except Exception as list_e:
             logging.error(f"SMBディレクトリ確認中に予期せぬエラー: {FILEHUB_SHARE}{full_path} - {list_e}", exc_info=True)
             raise

    except ValueError as e:
         logging.error(f"設定エラー: {e}")
         raise
    except Exception as e:
        logging.error(f"SMBディレクトリ操作中に予期せぬエラーが発生しました: {target_dir_pysmb} - {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()
            logging.info("SMB接続をクローズしました。")


def _check_duplicate_smb(target_dir_pysmb: str, local_filename: str) -> Optional[int]:
    """
    SMBディレクトリ内に同名のファイルが存在するか確認し、存在する場合はそのファイルサイズを返す (同期)。
    見つからない場合は None を返す。
    """
    conn = None
    try:
        conn = _get_smb_connection()
        assert conn.connect(FILEHUB_ADDRESS, 139)
        logging.info(f"SMB接続成功 (重複チェック): {FILEHUB_ADDRESS}")

        full_path = target_dir_pysmb
        logging.info(f"SMBディレクトリ内の重複を確認中: {FILEHUB_SHARE}{full_path} for file: {local_filename}")

        # 指定されたファイル名で直接属性を取得してみる
        remote_file_path = f"{full_path}/{local_filename}"
        try:
            attributes = conn.getAttributes(FILEHUB_SHARE, remote_file_path)
            logging.info(f"重複ファイルを発見しました: {local_filename} in {FILEHUB_SHARE}{full_path}, Size: {attributes.file_size}")
            return attributes.file_size
        except OperationFailure as e:
            # ファイルが存在しない場合のエラー (NT STATUS_OBJECT_NAME_NOT_FOUND など)
            logging.debug(f"SMBファイル属性取得失敗 (ファイルなし?): {FILEHUB_SHARE}{remote_file_path} - {e}")
            return None # ファイルが見つからない

    except OperationFailure as e:
         # ディレクトリが存在しない場合など
         logging.warning(f"SMBディレクトリまたはファイルの操作に失敗しました (重複チェック): {FILEHUB_SHARE}{full_path} - {e}")
         return None # ディレクトリがない場合もファイルは存在しないとみなす
    except ValueError as e:
         logging.error(f"設定エラー: {e}")
         raise
    except Exception as e:
        logging.error(f"SMB重複チェック中に予期せぬエラーが発生しました: {target_dir_pysmb}/{local_filename} - {e}", exc_info=True)
        # 予期せぬエラーの場合は安全側に倒して None を返す (アップロードを試みる)
        return None
    finally:
        if conn:
            conn.close()
            logging.info("SMB接続をクローズしました (重複チェック)。")


def _upload_file_smb(local_path: str, remote_path_pysmb: str, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
    """ファイルをSMBサーバーにアップロードする (同期)"""
    conn = None
    try:
        conn = _get_smb_connection()
        assert conn.connect(FILEHUB_ADDRESS, 139)
        logging.info(f"SMB接続成功 (アップロード): {FILEHUB_ADDRESS}")

        # リモートパス (共有名からの相対パス)
        # 例: /Adult/FC2-PPV-123/local_filename.mp4
        full_remote_path = remote_path_pysmb

        logging.info(f"SMBアップロード開始: {local_path} -> {FILEHUB_SHARE}{full_remote_path}")

        local_file_size = os.path.getsize(local_path)
        uploaded_size = 0
        chunk_size = 8192 # 8KB チャンク
        last_report_time = time.time()
        report_interval = 0.5 # 0.5秒ごとに進捗報告

        if progress_callback:
            progress_callback({"status": "uploading", "percentage": 0, "message": "アップロード開始", "uploaded_bytes": 0, "total_bytes": local_file_size})

        with open(local_path, 'rb') as local_file:
            # storeFile はファイルオブジェクトを受け付けるが、進捗を得るためにはチャンクで読み込む
            # pysmb の storeFile はファイルオブジェクト全体を渡すため、進捗コールバックを内部でサポートしていない
            # リアルタイム性を出すには、ファイルをチャンクに分けて読み込み、SMBConnection.storeFileFromOffset を使う必要がある
            # storeFileFromOffset は BytesIO のような seek/read を持つオブジェクトを期待する
            # 例: conn.storeFileFromOffset(service_name, path, file_obj, offset, max_length)

            # storeFileFromOffset を使うように修正
            offset = 0
            while offset < local_file_size:
                # チャンクを読み込む
                local_file.seek(offset)
                chunk = local_file.read(chunk_size)
                if not chunk:
                    break # ファイルの終端に達した

                # SMBに書き込む
                # storeFileFromOffset は BytesIO のような seek/read を持つオブジェクトを期待する
                chunk_io = BytesIO(chunk)
                conn.storeFileFromOffset(FILEHUB_SHARE, full_remote_path, chunk_io, offset, len(chunk))

                uploaded_size += len(chunk)
                offset += len(chunk)

                current_time = time.time()
                # 定期的に進捗報告
                if progress_callback and (current_time - last_report_time > report_interval):
                    percentage = (uploaded_size / local_file_size * 100) if local_file_size > 0 else 0
                    progress_callback({
                        "status": "uploading",
                        "percentage": round(percentage, 2),
                        "uploaded_bytes": uploaded_size,
                        "total_bytes": local_file_size,
                        "message": f"アップロード中 ({percentage:.2f}%)"
                    })
                    last_report_time = current_time

            # ループ終了後、最後の進捗報告 (100%)
            if progress_callback:
                 progress_callback({
                     "status": "uploading", # 完了直前も uploading ステータスで100%を報告
                     "percentage": 100.0,
                     "uploaded_bytes": local_file_size,
                     "total_bytes": local_file_size,
                     "message": "アップロード完了間近"
                 })


        logging.info(f"SMBアップロード完了: {FILEHUB_SHARE}{full_remote_path}")
        if progress_callback:
            progress_callback({"status": "finished", "percentage": 100, "message": "アップロード完了"})

    except FileNotFoundError:
        logging.error(f"ローカルファイルが見つかりません: {local_path}")
        if progress_callback:
            progress_callback({"status": "error", "message": "ローカルファイル不明"})
        raise
    except OperationFailure as e:
        logging.error(f"SMBアップロードエラーが発生しました: {FILEHUB_SHARE}{full_remote_path} - {e}", exc_info=True)
        if progress_callback:
            progress_callback({"status": "error", "message": f"SMBエラー: {e}"})
        raise
    except ValueError as e:
         logging.error(f"設定エラー: {e}")
         raise
    except Exception as e:
        logging.error(f"SMBアップロード中に予期せぬエラーが発生しました: {FILEHUB_SHARE}{full_remote_path} - {e}", exc_info=True)
        if progress_callback:
            progress_callback({"status": "error", "message": f"予期せぬエラー: {e}"})
        raise
    finally:
        if conn:
            conn.close()
            logging.info("SMB接続をクローズしました (アップロード)。")


# --- 統合アップロード関数 (非同期ラッパー) ---
async def upload_to_server(
    local_file_path: str,
    video_title: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None # 戻り値の型ヒントを Any に変更
) -> bool:
    """ダウンロードされたファイルを解析し、適切なフォルダにアップロードする"""
# 0. ローカルファイルの存在確認とダウンロード完了チェック
    if not local_file_path or not os.path.exists(local_file_path):
        logging.warning(f"ローカルファイルが存在しません: {local_file_path} (ダウンロード中または削除済み)")
        if progress_callback:
            # StatusManager にスキップを伝えるために progress_callback を呼び出す
            progress_callback({"status": "skipped", "message": "ローカルファイル未存在"})
        return True  # スキップも成功扱い (タスク完了とみなす)

    if local_file_path.endswith('.part'):
        logging.info(f"ファイルはダウンロード中です: {local_file_path}")
        if progress_callback:
            # StatusManager にスキップを伝えるために progress_callback を呼び出す
            progress_callback({"status": "skipped", "message": "ダウンロード中のファイルはスキップ"})
        return True  # スキップも成功扱い (タスク完了とみなす)
    logging.info(f"アップロード処理を開始: {local_file_path} (Title: {video_title})")

    # 1. タイトルからプレフィックスと完全IDを抽出
    prefix = extract_fc2_prefix(video_title)
    # full_id は重複チェックには使わないが、ログのために残しておく
    full_id = extract_fc2_full_id(video_title)

# 1.5. タイトルからプレフィックスを修正 (FC2-PPV-XXX → FC2-PPV-XX0)
    if prefix:
        # 最後の3桁を取得 (例: "123")
        number_part = prefix[-3:]
        # 最後の桁を0に置換 (例: "12" + "0" → "120")
        new_number = number_part[:2] + '0'
        # 新しいプレフィックスを構築 (例: "FC2-PPV-120")
        prefix = prefix[:-3] + new_number

    if not prefix:
        logging.error(f"タイトルからFC2-PPV-XXXプレフィックスが見つかりません: {video_title}")
        if progress_callback:
            progress_callback({"status": "error", "message": "タイトルからプレフィックス抽出失敗"})
        return False

    # 2. アップロード先ディレクトリパスを構築 (pysmb 用)
    # 例: /Adult/FC2-PPV-123
    target_dir_pysmb = f"{smb_base_path_pysmb}/{prefix}"

    # 3. リモートファイルパスを構築 (pysmb 用)
    # 例: /Adult/FC2-PPV-123/local_filename.mp4
    local_filename = os.path.basename(local_file_path)
    remote_file_path_pysmb = f"{target_dir_pysmb}/{local_filename}"

    try:
        # 4. ディレクトリ確認/作成 (非同期実行)
        await asyncio.to_thread(_check_or_create_smb_directory, target_dir_pysmb)

        # 5. 重複チェックと同名ファイルサイズ比較 (非同期実行)
        # _check_duplicate_smb を呼び出し、リモートファイルサイズを取得
        remote_file_size = await asyncio.to_thread(_check_duplicate_smb, target_dir_pysmb, local_filename)

        if remote_file_size is not None:
            # リモートに同名ファイルが存在する場合
            local_file_size = os.path.getsize(local_file_path)
            logging.info(f"リモートに同名ファイルが存在します: {local_filename}. ローカルサイズ: {local_file_size}, リモートサイズ: {remote_file_size}")

            if remote_file_size >= local_file_size:
                # リモートファイルの方が大きいか同じサイズの場合、アップロードをスキップ
                logging.info(f"リモートファイルの方が大きいか同じサイズのため、アップロードをスキップします: {local_filename}")
                if progress_callback:
                    # StatusManager にスキップを伝えるために progress_callback を呼び出す
                    progress_callback({"status": "skipped", "message": "サーバーに同名ファイル (サイズ大/同等) あり"})
                return True # スキップも成功扱い (タスク完了とみなす)
            else:
                # ローカルファイルの方が小さい場合、上書きしてアップロードを続行
                logging.info(f"ローカルファイルの方が小さいため、上書きしてアップロードを続行します: {local_filename}")
                # そのままアップロード処理に進む (_upload_file_smb はデフォルトで上書き)

        # 6. ファイルアップロード (非同期実行) - 重複がない場合、またはローカルファイルが小さい場合
        await asyncio.to_thread(_upload_file_smb, local_file_path, remote_file_path_pysmb, progress_callback)

        return True # アップロード成功

    except Exception as e:
        logging.error(f"アップロード処理全体でエラーが発生しました: {local_file_path} -> {target_dir_pysmb} - {e}", exc_info=True)
        if progress_callback:
             # エラー発生時も StatusManager にエラーを伝えるために progress_callback を呼び出す
             progress_callback({"status": "error", "message": f"アップロード処理エラー: {e}"})
        return False


# --- テスト用 (pysmb 用に修正が必要な場合がある) ---
# テストコードは pysmb の API に合わせて調整する必要があるため、一旦コメントアウト
# def test_upload_progress(progress_info: Dict[str, Any]):
#     """テスト用のアップロード進捗コールバック"""
#     status = progress_info.get("status")
#     message = progress_info.get("message", "")
#     percentage = progress_info.get("percentage", "")
#     print(f"Upload Status: {status}, Percentage: {percentage}%, Message: {message}")

# async def main_test():
#     # ... (pysmb 用のテストコードに修正) ...
#     pass

# if __name__ == '__main__':
#     try:
#         from smb.SMBConnection import SMBConnection
#     except ImportError:
#         print("エラー: pysmb がインストールされていません。")
#         print("pip install pysmb を実行してください。")
#     else:
#         # asyncio.run(main_test()) # テスト実行は別途調整
#         print("pysmb はインポート可能です。テスト実行はコメントアウトされています。")
#         pass