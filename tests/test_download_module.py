import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from src.download_module import DownloadManager
from queue import Queue # Queueをインポート
import time

@pytest.fixture
def download_manager():
    # テスト用に一時フォルダを作成
    test_temp_dir = "./test_temp_downloads"
    os.makedirs(test_temp_dir, exist_ok=True)
    manager = DownloadManager()
    manager.set_temp_folder(test_temp_dir)
    yield manager # テスト実行
    # テスト後クリーンアップ
    import shutil
    if os.path.exists(test_temp_dir):
        shutil.rmtree(test_temp_dir)


def test_download_manager_initialization(download_manager):
    """初期化状態を確認"""
    assert download_manager._temp_folder == "./test_temp_downloads" # fixtureで設定したパスを確認
    assert isinstance(download_manager.download_queue, Queue) # Queue型であることを確認
    assert download_manager.current_progress["status"] == "idle" # 初期ステータスを確認
    assert download_manager.current_progress["percentage"] == 0
    assert not download_manager.is_running() # is_runningメソッドで確認
    assert not download_manager._stop_event.is_set() # stop_eventを確認

def test_set_temp_folder(download_manager):
    """一時フォルダ設定のテスト"""
    new_folder = "./another_test_temp"
    os.makedirs(new_folder, exist_ok=True)
    download_manager.set_temp_folder(new_folder)
    assert download_manager._temp_folder == new_folder
    os.rmdir(new_folder) # 作成したフォルダを削除

    # 無効なパスでのエラーテスト
    with pytest.raises(ValueError):
        download_manager.set_temp_folder("./non_existent_folder")


def test_add_to_queue(download_manager):
    """キューへの追加テスト"""
    url1 = "https://www.youtube.com/watch?v=abc123"
    url2 = "https://www.youtube.com/watch?v=def456"
    download_manager.add_to_queue(url1, quality="highest")
    download_manager.add_to_queue(url2, quality="lowest")

    queue_status = download_manager.get_queue_status()
    assert len(queue_status) == 2
    assert queue_status[0]["url"] == url1
    assert queue_status[0]["quality"] == "highest"
    assert queue_status[1]["url"] == url2
    assert queue_status[1]["quality"] == "lowest"

# download_videoメソッドは削除されたため、関連テストも削除

# --- 実際のダウンロードを伴うテスト (時間がかかる可能性あり、モック化推奨) ---
# @pytest.mark.slow # 時間がかかるテストとしてマーク (pytest.iniで設定必要)
# def test_actual_download_and_progress(download_manager):
#     """実際のダウンロードと進捗確認 (モック未使用)"""
#     # 注意: 実際にネットワークアクセスとダウンロードが発生します
#     # テスト用の短い動画URLを使用することを推奨
#     test_url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ" # 例: Creative Commonsの短い動画
#     download_manager.add_to_queue(test_url)
#     download_manager.start_download()

#     max_wait_time = 60 # 最大待機時間 (秒)
#     start_time = time.time()
#     final_status = None

#     while time.time() - start_time < max_wait_time:
#         progress = download_manager.get_progress()
#         print(f"テスト進捗: {progress}") # デバッグ用
#         if progress["status"] == "completed":
#             final_status = "completed"
#             break
#         if progress["status"] == "error":
#             final_status = "error"
#             pytest.fail(f"ダウンロードエラー発生: {progress['error']}")
#             break
#         if not download_manager.is_running() and download_manager.download_queue.empty():
#              # スレッドが終了しキューも空になった場合
#              if progress["status"] != "completed": # まれに完了前にスレッドが終わるケース考慮
#                  final_status = progress["status"] # 完了以外の最終ステータス
#              break
#         time.sleep(1)

#     assert final_status == "completed", f"期待した完了ステータスが得られませんでした: {final_status}"
#     history = download_manager.get_history()
#     assert len(history) == 1
#     assert history[0]["url"] == test_url
#     assert history[0]["status"] == "completed"
#     assert os.path.exists(history[0]["path"]) # ファイルが実際に存在するか確認


# スキップされているテストはそのまま残す (将来的な実装のため)
@pytest.mark.skip(reason="中断・再開機能は未実装または複雑なためスキップ")
def test_download_interrupt_and_resume():
    pass

@pytest.mark.skip(reason="詳細な進捗コールバックのテストは未実装")
def test_download_progress_callback_details():
    pass