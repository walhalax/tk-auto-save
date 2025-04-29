import os
import threading
import time
import logging
from queue import Queue, Empty
from typing import Optional, Dict, Any, List, Tuple
import yt_dlp # youtube-dlからyt-dlpに変更

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DownloadManager:
    def __init__(self):
        self._temp_folder: str = "downloads" # デフォルトの一時フォルダ
        self.download_queue: Queue = Queue() # スレッドセーフなキューを使用
        self.download_history: List[Dict[str, Any]] = [] # ダウンロード履歴
        self.current_progress: Dict[str, Any] = {"url": None, "percentage": 0, "status": "idle", "filename": None, "error": None}
        self._stop_event: threading.Event = threading.Event() # キャンセル用イベント
        self._download_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock() # 状態更新時の排他制御用

    def set_temp_folder(self, folder_path: str):
        """一時フォルダのパスを設定"""
        with self._lock:
            if os.path.isdir(folder_path):
                self._temp_folder = folder_path
                logging.info(f"一時フォルダを設定: {self._temp_folder}")
            else:
                logging.error(f"無効なフォルダパス: {folder_path}")
                raise ValueError("無効なフォルダパスです。")

    def add_to_queue(self, url: str, quality: str = "best"):
        """ダウンロードキューにURLと品質を追加"""
        if not url:
            logging.warning("空のURLが指定されました。")
            return
        item = {"url": url, "quality": quality, "status": "queued"}
        self.download_queue.put(item)
        logging.info(f"キューに追加: {url} (品質: {quality})")

    def _progress_hook(self, d: Dict[str, Any]):
        """yt-dlpの進捗コールバック"""
        with self._lock:
            if d['status'] == 'downloading':
                filename = d.get('filename', 'N/A')
                # 一時ファイル名から最終的なファイル名を取得しようと試みる
                if '_tmp' in filename or '.part' in filename:
                     # yt-dlp 2023.07.06以降ではinfo_dict内に最終ファイル名が含まれることがある
                    info_dict = d.get('info_dict', {})
                    final_filename = info_dict.get('filename')
                    if final_filename:
                        filename = final_filename
                    else: # 古いバージョンや特定ケースのためのフォールバック
                        filename = os.path.splitext(filename.replace('.part', ''))[0] + '.' + info_dict.get('ext', 'mp4')


                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded_bytes = d.get('downloaded_bytes')

                if total_bytes and downloaded_bytes:
                    percentage = (downloaded_bytes / total_bytes) * 100
                    self.current_progress.update({
                        "percentage": percentage,
                        "status": "downloading",
                        "filename": os.path.basename(filename) if filename else "取得中...",
                        "error": None
                    })
                    # logging.debug(f"進捗: {percentage:.2f}% - {self.current_progress['filename']}") # デバッグ用
            elif d['status'] == 'finished':
                filename = d.get('filename', 'N/A')
                # info_dictから最終ファイル名を取得
                info_dict = d.get('info_dict', {})
                final_filename = info_dict.get('filename', filename) # filenameキーがない場合もあるためフォールバック

                self.current_progress.update({
                    "percentage": 100,
                    "status": "finished",
                    "filename": os.path.basename(final_filename) if final_filename else "完了",
                    "error": None
                })
                logging.info(f"ダウンロード完了: {self.current_progress['filename']}")
            elif d['status'] == 'error':
                error_msg = "ダウンロードエラーが発生しました。"
                self.current_progress.update({"status": "error", "error": error_msg, "percentage": self.current_progress.get("percentage", 0)})
                logging.error(error_msg)

    def _download_worker(self):
        """キューからURLを取得してダウンロードを実行するワーカースレッド"""
        while not self._stop_event.is_set():
            try:
                item = self.download_queue.get(timeout=1) # 1秒待機してキューをチェック
            except Empty:
                # キューが空なら待機
                time.sleep(1)
                continue

            url = item['url']
            quality = item['quality']
            logging.info(f"ダウンロード開始: {url} (品質: {quality})")

            with self._lock:
                self.current_progress = {"url": url, "percentage": 0, "status": "starting", "filename": "準備中...", "error": None}

            # yt-dlpオプション設定
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if quality == 'highest' else 'worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]/worst',
                'outtmpl': os.path.join(self._temp_folder, '%(title)s [%(id)s].%(ext)s'), # IDを含める
                'progress_hooks': [self._progress_hook],
                'nocheckcertificate': True, # 証明書チェックをスキップ (環境による問題を回避)
                'postprocessors': [{ # メタデータ埋め込みなど
                    'key': 'FFmpegMetadata',
                    'add_metadata': True,
                }, {
                    'key': 'EmbedThumbnail',
                    'already_have_thumbnail': False,
                }],
                'writethumbnail': True, # サムネイルも書き出す
                'writesubtitles': True, # 字幕も取得
                'writeautomaticsub': True, # 自動生成字幕も取得
                'subtitleslangs': ['en', 'ja'], # 字幕言語指定
                'merge_output_format': 'mp4', # 結合後のフォーマット
                # キャンセル処理のためのフックはyt-dlp自体には直接ないため、
                # スレッドの停止イベントを定期的にチェックする
                # 'external_downloader_args': ['--limit-rate', '1M'], # 必要なら速度制限
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # ダウンロード中にキャンセルをチェック
                    # yt-dlpはブロッキングするため、完全な中断は難しいが、
                    # フックやループで定期的にチェックするアプローチが考えられる
                    # ここではダウンロード完了後にチェックする形にする
                    info_dict = ydl.extract_info(url, download=True) # download=Trueでダウンロード実行
                    downloaded_path = ydl.prepare_filename(info_dict)

                if self._stop_event.is_set():
                    logging.info(f"ダウンロードキャンセル(完了後): {url}")
                    with self._lock:
                         self.current_progress.update({"status": "cancelled", "error": "ユーザーによりキャンセルされました。"})
                    # ダウンロードしたファイルを削除 (オプション)
                    if downloaded_path and os.path.exists(downloaded_path):
                        try:
                            os.remove(downloaded_path)
                            logging.info(f"キャンセルされたファイルを削除: {downloaded_path}")
                        except OSError as e:
                            logging.error(f"キャンセルされたファイルの削除に失敗: {e}")
                    continue # 次のアイテムへ

                # 履歴に追加
                history_entry = {
                    "url": url,
                    "title": info_dict.get('title', 'N/A'),
                    "filename": os.path.basename(downloaded_path) if downloaded_path else 'N/A',
                    "path": downloaded_path,
                    "quality": quality,
                    "status": "completed",
                    "timestamp": time.time()
                }
                self.download_history.append(history_entry)
                logging.info(f"履歴に追加: {history_entry['filename']}")

            except yt_dlp.utils.DownloadError as e:
                logging.error(f"yt-dlpダウンロードエラー: {url} - {e}")
                with self._lock:
                    self.current_progress.update({"status": "error", "error": f"ダウンロードエラー: {e}"})
                history_entry = {"url": url, "status": "failed", "error": str(e), "timestamp": time.time()}
                self.download_history.append(history_entry)
            except Exception as e:
                logging.error(f"予期せぬエラー: {url} - {e}")
                with self._lock:
                    self.current_progress.update({"status": "error", "error": f"予期せぬエラー: {e}"})
                history_entry = {"url": url, "status": "failed", "error": str(e), "timestamp": time.time()}
                self.download_history.append(history_entry)
            finally:
                self.download_queue.task_done() # キューのタスク完了を通知

        logging.info("ダウンロードワーカースレッド終了")
        with self._lock:
            # スレッド終了時にステータスをアイドルに戻すか検討
            if self.current_progress["status"] not in ["error", "cancelled"]:
                 self.current_progress = {"url": None, "percentage": 0, "status": "idle", "filename": None, "error": None}


    def start_download(self):
        """ダウンロード処理を別スレッドで開始"""
        if self._download_thread and self._download_thread.is_alive():
            logging.warning("ダウンロードは既に実行中です。")
            return

        self._stop_event.clear() # ストップイベントをリセット
        self._download_thread = threading.Thread(target=self._download_worker, daemon=True)
        self._download_thread.start()
        logging.info("ダウンロードワーカースレッド開始")

    def cancel_download(self):
        """進行中のダウンロードをキャンセル"""
        if not self._download_thread or not self._download_thread.is_alive():
            logging.warning("実行中のダウンロードはありません。")
            return

        logging.info("キャンセル要求を受信。")
        self._stop_event.set() # スレッドに停止を通知

        # yt-dlp自体を強制停止するのは難しいため、ワーカーループの終了を待つ
        # 必要であれば、サブプロセスをkillするなどのより強制的な手段も検討できるが複雑になる

        # キャンセル状態を即時反映
        with self._lock:
            if self.current_progress["status"] == "downloading":
                self.current_progress.update({"status": "cancelling", "error": "キャンセル処理中..."})


    def get_progress(self) -> Dict[str, Any]:
        """現在のダウンロード進捗を取得"""
        with self._lock:
            # return self.current_progress.copy() # shallow copyを返す
             # より安全にするためディープコピー、または必要な要素だけ返す
            return {
                "url": self.current_progress.get("url"),
                "percentage": self.current_progress.get("percentage", 0),
                "status": self.current_progress.get("status", "idle"),
                "filename": self.current_progress.get("filename"),
                "error": self.current_progress.get("error")
            }

    def get_queue_status(self) -> List[Dict[str, Any]]:
        """キューの内容を取得（表示用）"""
        # Queueオブジェクトは直接リスト化できないため、一時リストに入れる
        queue_list = list(self.download_queue.queue)
        return queue_list

    def get_history(self) -> List[Dict[str, Any]]:
        """ダウンロード履歴を取得"""
        return self.download_history

    def is_running(self) -> bool:
        """ダウンロードスレッドが実行中か確認"""
        return self._download_thread is not None and self._download_thread.is_alive()

# 使用例 (モジュールとしてインポートされる場合は実行されない)
if __name__ == '__main__':
    manager = DownloadManager()
    manager.set_temp_folder("./temp_downloads") # 一時フォルダ指定
    manager.add_to_queue("https://www.youtube.com/watch?v=dQw4w9WgXcQ", quality="highest")
    manager.add_to_queue("https://www.youtube.com/shorts/example_short_id") # 例: Shorts URL
    manager.add_to_queue("invalid_url") # 無効なURLの例

    manager.start_download()

    # 進捗を監視する例
    while manager.is_running() or not manager.download_queue.empty():
        progress = manager.get_progress()
        print(f"ステータス: {progress['status']}, 進捗: {progress['percentage']:.2f}%, ファイル: {progress['filename']}, URL: {progress['url']}, エラー: {progress['error']}")
        queue_items = manager.get_queue_status()
        print(f"キュー残り: {len(queue_items)}件")
        time.sleep(2)
        # 特定のタイミングでキャンセルする例
        # if progress['percentage'] > 10:
        #     print("10%超えたのでキャンセルします")
        #     manager.cancel_download()
        #     break

    print("\nダウンロード処理完了")
    print("\nダウンロード履歴:")
    for entry in manager.get_history():
        print(f"- {entry['filename']} ({entry['status']}) - {entry.get('error', '')}")

    print("\n最終進捗:")
    print(manager.get_progress())