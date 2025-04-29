import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional, Set, Tuple, List
from collections import deque
from datetime import datetime # ★★★ インポート追加 ★★★

# ロギング設定
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s')

STATUS_FILE = "task_status.json"

class StatusManager:
    def __init__(self, status_file=STATUS_FILE):
        self.status_file = status_file
        self._lock = asyncio.Lock()
        # メモリ上の状態 (ファイルは永続化用)
        self.task_status: Dict[str, Dict[str, Any]] = {} # {fc2_id: {"status": "...", "progress": ..., ...}}
        self.download_queue: deque[str] = deque() # ダウンロード待ちの fc2_id
        self.upload_queue: deque[str] = deque()   # アップロード待ちの fc2_id
        self.processed_ids: Set[str] = set()      # 完了/スキップ済みの fc2_id
        self.stop_requested: bool = False         # 停止リクエストフラグ

        # 起動時にファイルから状態を読み込む
        asyncio.create_task(self._load_status())

    async def _load_status(self):
        """状態ファイルからステータスを読み込む"""
        async with self._lock:
            if os.path.exists(self.status_file):
                try:
                    with open(self.status_file, 'r') as f:
                        data = json.load(f)
                        self.task_status = data.get('task_status', {})
                        self.download_queue = deque(data.get('download_queue', []))
                        self.upload_queue = deque(data.get('upload_queue', []))
                        self.processed_ids = set(data.get('processed_ids', []))
                        logging.info(f"状態ファイルを読み込みました: {len(self.task_status)} tasks, {len(self.download_queue)} DL queue, {len(self.upload_queue)} UL queue, {len(self.processed_ids)} processed.")
                        # 整合性チェック (キューにあるIDがtask_statusに存在するかなど) を追加しても良い
                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f"状態ファイルの読み込みに失敗しました: {e}. 新しい状態で開始します。")
                    self._reset_state() # エラー時はリセット
            else:
                logging.info("状態ファイルが見つかりません。新しい状態で開始します。")
                self._reset_state()

    async def _save_status(self):
        """現在のステータスを状態ファイルに保存する"""
        # ロックは呼び出し元で取得されている想定
        try:
            data_to_save = {
                'task_status': self.task_status,
                'download_queue': list(self.download_queue),
                'upload_queue': list(self.upload_queue),
                'processed_ids': list(self.processed_ids)
            }
            with open(self.status_file, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            logging.debug("状態をファイルに保存しました。")
        except IOError as e:
            logging.error(f"状態ファイルの保存に失敗しました: {e}")

    def _reset_state(self):
        """メモリ上の状態をリセットする (非同期ではない内部用)"""
        self.task_status = {}
        self.download_queue = deque()
        self.upload_queue = deque()
        self.processed_ids = set()
        self.stop_requested = False

    async def reset_state_async(self):
        """メモリ上の状態をリセットし、ファイルに保存する (外部呼び出し用)"""
        async with self._lock:
            logging.info("タスクステータスをリセットします。")
            self._reset_state()
            await self._save_status()
            logging.info("タスクステータスのリセットが完了しました。")


    async def add_download_task(self, video_info: Dict[str, Any]):
        """新しいダウンロードタスクをキューとステータスに追加する"""
        fc2_id = video_info.get('fc2_id')
        if not fc2_id:
            logging.warning("FC2 ID がないためタスクを追加できません。")
            return

        async with self._lock:
            if fc2_id not in self.task_status and fc2_id not in self.processed_ids:
                self.task_status[fc2_id] = {
                    "status": "pending_download",
                    "title": video_info.get('title'),
                    "url": video_info.get('url'),
                    "added_date": video_info.get('added_date_str'),
                    "rating": video_info.get('rating'),
                    "download_progress": 0,
                    "upload_progress": 0,
                    "local_path": None,
                    "error_message": None,
                    "last_updated": datetime.now().isoformat() # ここで datetime を使用
                }
                self.download_queue.append(fc2_id)
                logging.info(f"ダウンロードキューに追加: {fc2_id} - {video_info.get('title')}")
                await self._save_status() # 状態を保存
            else:
                logging.debug(f"タスクは既に存在するか処理済みです: {fc2_id}")

    async def get_next_download_task(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """ダウンロードキューから次のタスクを取得し、状態を 'downloading' に更新する"""
        async with self._lock:
            if self.stop_requested:
                logging.debug("停止リクエスト中のため、新しいダウンロードタスクは取得しません。")
                return None
            if not self.download_queue:
                logging.debug("ダウンロードキューは空です。")
                return None

            fc2_id = self.download_queue.popleft()
            if fc2_id in self.task_status:
                self.task_status[fc2_id].update({
                    "status": "downloading",
                    "download_progress": 0, # 開始時にリセット
                    "error_message": None,
                    "last_updated": datetime.now().isoformat()
                })
                logging.info(f"次のダウンロードタスクを取得: {fc2_id}")
                task_info = self.task_status[fc2_id]
                await self._save_status() # 状態を保存
                # タスク情報に必要なキーを追加 (ワーカーが必要とする情報)
                task_info_for_worker = {
                    "title": task_info.get("title"),
                    "video_page_url": task_info.get("url") # download_module が使うURL
                }
                return fc2_id, task_info_for_worker
            else:
                logging.warning(f"キューにあったID {fc2_id} が task_status に存在しません。")
                # キューから削除されたので、状態保存は不要
                return None # 見つからない場合はNoneを返す

    async def update_download_progress(self, fc2_id: str, progress_data: Dict[str, Any]):
        """ダウンロードの進捗や状態を更新する"""
        async with self._lock:
            if fc2_id in self.task_status:
                current_task = self.task_status[fc2_id]
                current_task.update(progress_data) # status, progress, message など
                current_task["last_updated"] = datetime.now().isoformat()

                new_status = progress_data.get("status")
                logging.debug(f"ダウンロード進捗更新: {fc2_id} - Status: {new_status}, Data: {progress_data}")

                if new_status == "finished":
                    logging.info(f"ダウンロード完了: {fc2_id}")
                    # 完了したらアップロードキューに追加
                    if fc2_id not in self.upload_queue:
                         # finished 時に local_path が progress_data に含まれるか、
                         # set_download_local_path で設定されている必要がある
                         if current_task.get("local_path"):
                              self.upload_queue.append(fc2_id)
                              current_task["status"] = "pending_upload" # ステータスを更新
                              logging.info(f"アップロードキューに追加: {fc2_id}")
                         else:
                              logging.error(f"ダウンロード完了報告がありましたが、ローカルパスが不明です: {fc2_id}")
                              current_task["status"] = "error"
                              current_task["error_message"] = "ダウンロード完了後ローカルパス不明"
                elif new_status == "error" or new_status == "failed_download":
                    logging.error(f"ダウンロード失敗/エラー: {fc2_id} - {progress_data.get('message')}")
                    # processed_ids には追加しない (リセット可能にするため)
                elif new_status == "skipped":
                     logging.info(f"ダウンロードスキップ: {fc2_id} - {progress_data.get('message')}")
                     self.processed_ids.add(fc2_id) # スキップは処理済みとする
                     # task_status から削除するかどうか？ 일단残す

                await self._save_status() # 状態を保存
            else:
                logging.warning(f"進捗更新対象のタスクが見つかりません: {fc2_id}")

    async def set_download_local_path(self, fc2_id: str, local_path: str):
        """ダウンロード完了後のローカルファイルパスを設定する"""
        async with self._lock:
            if fc2_id in self.task_status:
                self.task_status[fc2_id]["local_path"] = local_path
                self.task_status[fc2_id]["last_updated"] = datetime.now().isoformat()
                logging.debug(f"ローカルパスを設定: {fc2_id} -> {local_path}")
                await self._save_status()

    async def get_next_upload_task(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """アップロードキューから次のタスクを取得し、状態を 'uploading' に更新する"""
        async with self._lock:
            if self.stop_requested:
                logging.debug("停止リクエスト中のため、新しいアップロードタスクは取得しません。")
                return None
            if not self.upload_queue:
                logging.debug("アップロードキューは空です。")
                return None

            fc2_id = self.upload_queue.popleft()
            if fc2_id in self.task_status:
                self.task_status[fc2_id].update({
                    "status": "uploading",
                    "upload_progress": 0, # 開始時にリセット
                    "error_message": None,
                    "last_updated": datetime.now().isoformat()
                })
                logging.info(f"次のアップロードタスクを取得: {fc2_id}")
                task_info = self.task_status[fc2_id]
                await self._save_status() # 状態を保存
                # ワーカーに必要な情報を渡す
                task_info_for_worker = {
                    "title": task_info.get("title"),
                    "local_path": task_info.get("local_path")
                }
                return fc2_id, task_info_for_worker
            else:
                logging.warning(f"キューにあったID {fc2_id} が task_status に存在しません。")
                return None

    async def update_upload_progress(self, fc2_id: str, progress_data: Dict[str, Any]):
        """アップロードの進捗や状態を更新する"""
        async with self._lock:
            if fc2_id in self.task_status:
                current_task = self.task_status[fc2_id]
                current_task.update(progress_data)
                current_task["last_updated"] = datetime.now().isoformat()

                new_status = progress_data.get("status")
                logging.debug(f"アップロード進捗更新: {fc2_id} - Status: {new_status}, Data: {progress_data}")

                if new_status == "finished" or new_status == "skipped": # スキップも完了扱い
                    message = progress_data.get('message', '完了')
                    logging.info(f"アップロード完了/スキップ: {fc2_id} - {message}")
                    self.processed_ids.add(fc2_id) # 処理済みに追加
                    current_task["status"] = "completed" if new_status == "finished" else "skipped_upload"
                elif new_status == "error" or new_status == "failed_upload":
                    logging.error(f"アップロード失敗/エラー: {fc2_id} - {progress_data.get('message')}")
                    # processed_ids には追加しない

                await self._save_status() # 状態を保存
            else:
                logging.warning(f"進捗更新対象のタスクが見つかりません: {fc2_id}")

    async def get_all_status(self) -> Dict[str, Any]:
        """現在のすべてのタスクステータスとキュー情報を返す"""
        async with self._lock:
            # task_status のコピーを返す (深いコピーが必要な場合もあるが、今回は浅いコピーで十分か)
            status_copy = {k: v.copy() for k, v in self.task_status.items()}
            return {
                "task_status": status_copy,
                "download_queue_count": len(self.download_queue),
                "upload_queue_count": len(self.upload_queue),
                "processed_count": len(self.processed_ids)
            }

    async def get_processed_ids(self) -> Set[str]:
        """処理済みのIDセットを返す"""
        async with self._lock:
            return self.processed_ids.copy()

    async def get_task_status(self, fc2_id: str) -> Optional[Dict[str, Any]]:
        """指定されたタスクの現在のステータスを返す"""
        async with self._lock:
            task = self.task_status.get(fc2_id)
            return task.copy() if task else None

    async def request_stop(self):
        """停止リクエストフラグを立てる"""
        async with self._lock:
            self.stop_requested = True
            logging.info("停止リクエストを受け付けました。")

    async def clear_stop_request(self):
        """停止リクエストフラグをクリアする"""
        async with self._lock:
            self.stop_requested = False
            logging.info("停止リクエストをクリアしました。")

    async def resume_paused_tasks(self):
        """'paused' 状態のタスクを適切なキューに戻す"""
        async with self._lock:
            resumed_dl = 0
            resumed_ul = 0
            ids_to_process = list(self.task_status.keys()) # イテレーション中の変更を避ける

            for fc2_id in ids_to_process:
                task = self.task_status.get(fc2_id)
                if task and task.get("status") == "paused":
                    # paused の前の状態や情報に基づいてキューに戻す
                    # 簡単な実装: local_path があればアップロード、なければダウンロードに戻す
                    if task.get("local_path") and fc2_id not in self.upload_queue:
                        self.upload_queue.appendleft(fc2_id) # 先頭に戻す
                        task["status"] = "pending_upload"
                        task["last_updated"] = datetime.now().isoformat() # ★★★ 更新時刻 ★★★
                        resumed_ul += 1
                        logging.info(f"中断されたアップロードタスクを再開キューに追加: {fc2_id}")
                    elif not task.get("local_path") and fc2_id not in self.download_queue:
                        self.download_queue.appendleft(fc2_id) # 先頭に戻す
                        task["status"] = "pending_download"
                        task["last_updated"] = datetime.now().isoformat() # ★★★ 更新時刻 ★★★
                        resumed_dl += 1
                        logging.info(f"中断されたダウンロードタスクを再開キューに追加: {fc2_id}")
                    else:
                        logging.warning(f"状態 'paused' のタスク {fc2_id} をどのキューに戻すべきか判断できませんでした。")
                        # エラー状態にするか？
                        task["status"] = "error"
                        task["error_message"] = "再開処理エラー"
                        task["last_updated"] = datetime.now().isoformat() # ★★★ 更新時刻 ★★★

            if resumed_dl > 0 or resumed_ul > 0:
                logging.info(f"{resumed_dl}件のダウンロード、{resumed_ul}件のアップロードを再開キューに追加しました。")
                await self._save_status()

    async def reset_failed_tasks(self):
        """'error', 'failed_download', 'failed_upload' 状態のタスクをリセットしてダウンロードキューに戻す"""
        async with self._lock:
            reset_count = 0
            ids_to_process = list(self.task_status.keys())
            
            # processed_ids から失敗したタスクのIDを一時的に削除
            failed_ids_in_processed = [
                fc2_id for fc2_id, task in self.task_status.items()
                if task and (task.get("status", "").startswith("fail") or task.get("status") == "error")
                and fc2_id in self.processed_ids
            ]
            for fc2_id in failed_ids_in_processed:
                self.processed_ids.remove(fc2_id)
                logging.debug(f"processed_ids から失敗タスク {fc2_id} を一時削除")


            for fc2_id in ids_to_process:
                task = self.task_status.get(fc2_id)
                if task and (task.get("status", "").startswith("fail") or task.get("status") == "error"):
                    if fc2_id not in self.download_queue:
                        # 状態をリセット
                        task["status"] = "pending_download"
                        task["download_progress"] = 0
                        task["upload_progress"] = 0
                        task["local_path"] = None
                        task["error_message"] = None
                        task["last_updated"] = datetime.now().isoformat()
                        self.download_queue.appendleft(fc2_id) # 再試行のため先頭に追加
                        reset_count += 1
                        logging.info(f"失敗したタスクをリセットし、ダウンロードキューに追加: {fc2_id}")
                    else:
                        logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在するため、リセットのみ行います。")
                        task["status"] = "pending_download"
                        task["download_progress"] = 0
                        task["upload_progress"] = 0
                        task["local_path"] = None
                        task["error_message"] = None
                        task["last_updated"] = datetime.now().isoformat()


            if reset_count > 0 or failed_ids_in_processed: # processed_ids から削除があった場合も保存
                logging.info(f"{reset_count} 件の失敗したタスクをリセットしました。")
                await self._save_status()