import asyncio
import json
import logging
import os
from typing import Dict, Any, Optional, Set, Tuple, List
from collections import deque
from datetime import datetime
import re # FC2 ID 抽出用にインポート

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
            logging.debug("状態ファイルの読み込みを開始します。") # デバッグログ追加
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
                        logging.debug(f"読み込み後のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
                        logging.debug(f"読み込み後のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
                        logging.debug(f"読み込み後のupload_queue: {list(self.upload_queue)}") # デバッグログ維持
                        # 各タスクの状態を個別にログ出力 (詳細)
                        for fc2_id, task_info in self.task_status.items():
                             logging.debug(f"読み込みタスク状態: {fc2_id} - Status: {task_info.get('status')}, LocalPath: {task_info.get('local_path')}, DL_Progress: {task_info.get('download_progress')}, UL_Progress: {task_info.get('upload_progress')}") # デバッグログ追加

                except (json.JSONDecodeError, IOError) as e:
                    logging.error(f"状態ファイルの読み込みに失敗しました: {e}. 新しい状態で開始します。")
                    self._reset_state() # エラー時はリセット
            else:
                logging.info("状態ファイルが見つかりません。新しい状態で開始します。")
                self._reset_state()
            logging.debug("状態ファイルの読み込みを完了しました。") # デバッグログ追加


    async def _save_status(self):
        """現在のステータスを状態ファイルに保存する"""
        # ロックは呼び出し元で取得されている想定
        logging.debug("状態ファイルの保存を開始します。") # デバッグログ追加
        try:
            data_to_save = {
                'task_status': self.task_status,
                'download_queue': list(self.download_queue),
                'upload_queue': list(self.upload_queue),
                'processed_ids': list(self.processed_ids)
            }
            with open(self.status_file, 'w') as f:
                json.dump(data_to_save, f, indent=4)
            logging.debug("状態をファイルに保存しました。") # デバッグログ維持
        except IOError as e:
            logging.error(f"状態ファイルの保存に失敗しました: {e}")
        logging.debug("状態ファイルの保存を完了しました。") # デバッグログ追加


    def _reset_state(self):
        """メモリ上の状態をリセットする (非同期ではない内部用)"""
        logging.debug("メモリ上の状態をリセットします。") # デバッグログ追加
        self.task_status = {}
        self.download_queue = deque()
        self.upload_queue = deque()
        self.processed_ids = set()
        self.stop_requested = False
        logging.debug("メモリ上の状態のリセットが完了しました。") # デバッグログ追加


    async def reset_state_async(self):
        """メモリ上の状態をリセットし、ファイルに保存する (外部呼び出し用)"""
        async with self._lock:
            logging.info("タスクステータスをリセットします。") # ログ維持
            self._reset_state()
            await self._save_status()
            logging.info("タスクステータスのリセットが完了しました。") # ログ維持


    async def add_download_task(self, video_info: Dict[str, Any]):
        """新しいダウンロードタスクをキューとステータスに追加する"""
        fc2_id = video_info.get('fc2_id')
        if not fc2_id:
            logging.warning("FC2 ID がないためタスクを追加できません。") # ログ維持
            return

        async with self._lock:
            logging.debug(f"ダウンロードタスク追加処理開始: {fc2_id}") # デバッグログ追加
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
                logging.info(f"ダウンロードキューに追加: {fc2_id} - {video_info.get('title')}") # ログ維持
                await self._save_status() # 状態を保存
                logging.debug(f"ダウンロードタスク {fc2_id} を追加し、状態を保存しました。") # デバッグログ追加
            else:
                logging.debug(f"タスクは既に存在するか処理済みです: {fc2_id}") # ログ維持
            logging.debug(f"ダウンロードタスク追加処理完了: {fc2_id}") # デバッグログ追加


    async def get_next_download_task(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """ダウンロードキューから次のタスクを取得し、状態を 'downloading' に更新する"""
        async with self._lock:
            logging.debug("次のダウンロードタスク取得処理開始。") # デバッグログ追加
            if self.stop_requested:
                logging.debug("停止リクエスト中のため、新しいダウンロードタスクは取得しません。") # ログ維持
                logging.debug("次のダウンロードタスク取得処理完了 (停止リクエスト)。") # デバッグログ追加
                return None
            if not self.download_queue:
                logging.debug("ダウンロードキューは空です。") # ログ維持
                logging.debug("次のダウンロードタスク取得処理完了 (キュー空)。") # デバッグログ追加
                return None

            fc2_id = self.download_queue.popleft()
            logging.debug(f"キューからタスク {fc2_id} を取得しました。") # デバッグログ追加
            if fc2_id in self.task_status:
                self.task_status[fc2_id].update({
                    "status": "downloading",
                    "download_progress": 0, # 開始時にリセット
                    "error_message": None,
                    "last_updated": datetime.now().isoformat()
                })
                logging.info(f"次のダウンロードタスクを取得: {fc2_id}") # ログ維持
                task_info = self.task_status[fc2_id]
                await self._save_status() # 状態を保存
                logging.debug(f"タスク {fc2_id} の状態をdownloadingに更新し、保存しました。") # デバッグログ追加
                # タスク情報に必要なキーを追加 (ワーカーが必要とする情報)
                task_info_for_worker = {
                    "title": task_info.get("title"),
                    "video_page_url": task_info.get("url") # download_module が使うURL
                }
                logging.debug(f"次のダウンロードタスク取得処理完了: {fc2_id}") # デバッグログ追加
                return fc2_id, task_info_for_worker
            else:
                logging.warning(f"キューにあったID {fc2_id} が task_status に存在しません。") # ログ維持
                # キューから削除されたので、状態保存は不要
                logging.debug("次のダウンロードタスク取得処理完了 (タスク不明)。") # デバッグログ追加
                return None # 見つからない場合はNoneを返す
            
    async def update_download_progress(self, fc2_id: str, progress_data: Dict[str, Any]):
        """ダウンロードの進捗や状態を更新する"""
        async with self._lock:
            logging.debug(f"ダウンロード進捗更新処理開始: {fc2_id}") # デバッグログ追加
            if fc2_id in self.task_status:
                current_task = self.task_status[fc2_id]
                # Progressデータ全体を更新しつつ、percentageをdownload_progressに明示的に設定
                current_task.update(progress_data)
                current_task["download_progress"] = progress_data.get("percentage", 0) # percentage を保存
                current_task["last_updated"] = datetime.now().isoformat()

                new_status = progress_data.get("status")
                logging.debug(f"ダウンロード進捗更新: {fc2_id} - Status: {new_status}, Data: {progress_data}") # ログ維持

                if new_status == "finished":
                    logging.info(f"ダウンロード完了: {fc2_id}") # ログ維持
                    # 完了したらアップロードキューに追加
                    if fc2_id not in self.upload_queue:
                         # finished 時に local_path が progress_data に含まれるか、
                         # set_download_local_path で設定されている必要がある
                         if current_task.get("local_path"):
                              self.upload_queue.append(fc2_id)
                              current_task["status"] = "pending_upload" # ステータスを更新
                              logging.info(f"アップロードキューに追加: {fc2_id}") # ログ維持
                         else:
                              logging.error(f"ダウンロード完了報告がありましたが、ローカルパスが不明です: {fc2_id}") # ログ維持
                              current_task["status"] = "error"
                              current_task["error_message"] = "ダウンロード完了後ローカルパス不明"
                    logging.debug(f"ダウンロード完了処理: {fc2_id} - アップロードキュー追加チェック完了。") # デバッグログ追加
                elif new_status == "error" or new_status == "failed_download":
                    logging.error(f"ダウンロード失敗/エラー: {fc2_id} - {progress_data.get('message')}") # ログ維持
                    # processed_ids には追加しない (リセット可能にするため)
                    logging.debug(f"ダウンロード失敗処理: {fc2_id} - processed_idsに追加しません。") # デバッグログ追加
                elif new_status == "skipped":
                     logging.info(f"ダウンロードスキップ: {fc2_id} - {progress_data.get('message')}") # ログ維持
                     self.processed_ids.add(fc2_id) # スキップは処理済みとする
                     # task_status から削除するかどうか？ 일단残す
                     logging.debug(f"ダウンロードスキップ処理: {fc2_id} - processed_idsに追加しました。") # デバッグログ追加
                elif new_status == "paused": # paused 状態の更新を追加
                     logging.info(f"ダウンロード中断: {fc2_id} - {progress_data.get('message')}") # ログ追加
                     current_task["status"] = "paused"
                     logging.debug(f"ダウンロード中断処理: {fc2_id} - 状態をpausedに更新しました。") # デバッグログ追加


                await self._save_status() # 状態を保存
                logging.debug(f"ダウンロード進捗更新処理完了: {fc2_id} - 状態を保存しました。") # デバッグログ追加
            else:
                logging.warning(f"進捗更新対象のタスクが見つかりません: {fc2_id}") # ログ維持
                logging.debug(f"ダウンロード進捗更新処理完了: {fc2_id} - タスクが見つかりませんでした。") # デバッグログ追加


    async def set_download_local_path(self, fc2_id: str, local_path: str):
        """ダウンロード完了後のローカルファイルパスを設定する"""
        async with self._lock:
            logging.debug(f"ローカルパス設定処理開始: {fc2_id} -> {local_path}") # デバッグログ追加
            if fc2_id in self.task_status:
                self.task_status[fc2_id]["local_path"] = local_path
                self.task_status[fc2_id]["last_updated"] = datetime.now().isoformat()
                logging.debug(f"ローカルパスを設定: {fc2_id} -> {local_path}") # ログ維持
                await self._save_status()
                logging.debug(f"ローカルパス設定処理完了: {fc2_id} - 状態を保存しました。") # デバッグログ追加
            else:
                logging.warning(f"ローカルパス設定対象のタスクが見つかりません: {fc2_id}") # ログ維持
                logging.debug(f"ローカルパス設定処理完了: {fc2_id} - タスクが見つかりませんでした。") # デバッグログ追加


    async def get_next_upload_task(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """アップロードキューから次のタスクを取得し、状態を 'uploading' に更新する"""
        async with self._lock:
            logging.debug("次のアップロードタスク取得処理開始。") # デバッグログ追加
            if self.stop_requested:
                logging.debug("停止リクエスト中のため、新しいアップロードタスクは取得しません。") # ログ維持
                logging.debug("次のアップロードタスク取得処理完了 (停止リクエスト)。") # デバッグログ追加
                return None
            if not self.upload_queue:
                logging.debug("アップロードキューは空です。") # ログ維持
                logging.debug("次のアップロードタスク取得処理完了 (キュー空)。") # デバッグログ追加
                return None

            fc2_id = self.upload_queue.popleft()
            logging.debug(f"キューからアップロードタスク {fc2_id} を取得しました。") # デバッグログ追加
            if fc2_id in self.task_status:
                self.task_status[fc2_id].update({
                    "status": "uploading",
                    "upload_progress": 0, # 開始時にリセット
                    "error_message": None,
                    "last_updated": datetime.now().isoformat()
                })
                logging.info(f"次のアップロードタスクを取得: {fc2_id}") # ログ維持
                task_info = self.task_status[fc2_id]
                await self._save_status() # 状態を保存
                logging.debug(f"タスク {fc2_id} の状態をuploadingに更新し、保存しました。") # デバッグログ追加
                # ワーカーに必要な情報を渡す
                task_info_for_worker = {
                    "title": task_info.get("title"),
                    "local_path": task_info.get("local_path")
                }
                logging.debug(f"次のアップロードタスク取得処理完了: {fc2_id}") # デバッグログ追加
                return fc2_id, task_info_for_worker
            else:
                logging.warning(f"キューにあったID {fc2_id} が task_status に存在しません。") # ログ維持
                logging.debug("次のアップロードタスク取得処理完了 (タスク不明)。") # デバッグログ追加
                return None

    async def update_upload_progress(self, fc2_id: str, progress_data: Dict[str, Any]):
        """アップロードの進捗や状態を更新する"""
        async with self._lock:
            logging.debug(f"アップロード進捗更新処理開始: {fc2_id}") # デバッグログ追加
            if fc2_id in self.task_status:
                current_task = self.task_status[fc2_id]
                # Progressデータ全体を更新しつつ、percentageをupload_progressに明示的に設定
                current_task.update(progress_data)
                current_task["upload_progress"] = progress_data.get("percentage", 0) # percentage を保存
                current_task["last_updated"] = datetime.now().isoformat()

                new_status = progress_data.get("status")
                logging.debug(f"アップロード進捗更新: {fc2_id} - Status: {new_status}, Data: {progress_data}") # ログ維持

                if new_status == "finished" or new_status == "skipped": # スキップも完了扱い
                    message = progress_data.get('message', '完了')
                    logging.info(f"アップロード完了/スキップ: {fc2_id} - {message}") # ログ維持
                    self.processed_ids.add(fc2_id) # 処理済みに追加
                    current_task["status"] = "completed" if new_status == "finished" else "skipped_upload"
                    logging.debug(f"アップロード完了/スキップ処理: {fc2_id} - processed_idsに追加しました。") # デバッグログ追加
                elif new_status == "error" or new_status == "failed_upload":
                    logging.error(f"アップロード失敗/エラー: {fc2_id} - {progress_data.get('message')}") # ログ維持
                    # processed_ids には追加しない
                    logging.debug(f"アップロード失敗処理: {fc2_id} - processed_idsに追加しません。") # デバッグログ追加
                elif new_status == "paused": # paused 状態の更新を追加
                     logging.info(f"アップロード中断: {fc2_id} - {progress_data.get('message')}") # ログ追加
                     current_task["status"] = "paused"
                     logging.debug(f"アップロード中断処理: {fc2_id} - 状態をpausedに更新しました。") # デバッグログ追加


                await self._save_status() # 状態を保存
                logging.debug(f"アップロード進捗更新処理完了: {fc2_id} - 状態を保存しました。") # デバッグログ追加
            else:
                logging.warning(f"進捗更新対象のタスクが見つかりません: {fc2_id}") # ログ維持
                logging.debug(f"アップロード進捗更新処理完了: {fc2_id} - タスクが見つかりませんでした。") # デバッグログ追加


    async def get_all_status(self) -> Dict[str, Any]:
        """現在のすべてのタスクステータスとキュー情報を返す"""
        async with self._lock:
            logging.debug("全タスクステータス取得処理開始。") # デバッグログ追加
            # task_status のコピーを作成
            status_copy = {k: v.copy() for k, v in self.task_status.items()}

            # フロントエンドが必要とする 'progress' フィールドを追加
            for task_id, task_info in status_copy.items():
                status = task_info.get("status")
                if status == "downloading":
                    task_info["progress"] = task_info.get("download_progress", 0)
                elif status == "uploading":
                    task_info["progress"] = task_info.get("upload_progress", 0)
                elif status == "completed" or status == "skipped":
                     # 完了/スキップの場合は100%または0%など、適切な値を設定
                     task_info["progress"] = 100.0 if status == "completed" else 0.0
                else:
                    task_info["progress"] = 0.0 # その他の状態では0%

            logging.debug("全タスクステータス取得処理完了。") # デバッグログ追加
            return {
                "task_status": status_copy,
                "download_queue_count": len(self.download_queue),
                "upload_queue_count": len(self.upload_queue),
                "processed_count": len(self.processed_ids)
            }

    async def get_processed_ids(self) -> Set[str]:
        """処理済みのIDセットを返す"""
        async with self._lock:
            logging.debug("処理済みID取得処理開始/完了。") # デバッグログ追加
            return self.processed_ids.copy()
            
    async def get_task_status(self, fc2_id: str) -> Optional[Dict[str, Any]]:
        """指定されたタスクの現在のステータスを返す"""
        async with self._lock:
            logging.debug(f"タスクステータス取得処理開始: {fc2_id}") # デバッグログ追加
            task = self.task_status.get(fc2_id)
            if task:
                 task_copy = task.copy()
                 # フロントエンドが必要とする 'progress' フィールドを追加
                 status = task_copy.get("status")
                 if status == "downloading":
                     task_copy["progress"] = task_copy.get("download_progress", 0)
                 elif status == "uploading":
                     task_copy["progress"] = task_copy.get("upload_progress", 0)
                 elif status == "completed" or status == "skipped":
                      task_copy["progress"] = 100.0 if status == "completed" else 0.0
                 else:
                     task_copy["progress"] = 0.0
                 logging.debug(f"タスクステータス取得処理完了: {fc2_id} - タスク見つかりました。") # デバッグログ追加
                 return task_copy
            logging.debug(f"タスクステータス取得処理完了: {fc2_id} - タスク見つかりませんでした。") # デバッグログ追加
            return None


    async def request_stop(self):
        """停止リクエストフラグを立てる"""
        async with self._lock:
            logging.debug("停止リクエスト処理開始。") # デバッグログ追加
            self.stop_requested = True
            logging.info("停止リクエストを受け付けました。") # ログ維持
            logging.debug("停止リクエスト処理完了。") # デバッグログ追加


    async def clear_stop_request(self):
        """停止リクエストフラグをクリアする"""
        async with self._lock:
            logging.debug("停止リクエストクリア処理開始。") # デバッグログ追加
            self.stop_requested = False
            logging.info("停止リクエストをクリアしました。") # ログ維持
            logging.debug("停止リクエストクリア処理完了。") # デバッグログ追加


    async def resume_paused_tasks(self):
        """'paused' 状態のタスクを適切なキューに戻す"""
        async with self._lock:
            logging.info("中断されたタスクのレジューム処理を開始します。") # ログ維持
            logging.debug(f"レジューム処理開始時のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
            logging.debug(f"レジューム処理開始時のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
            logging.debug(f"レジューム処理開始時のupload_queue: {list(self.upload_queue)}") # デバッグログ維持
            resumed_dl = 0
            resumed_ul = 0
            ids_to_process = list(self.task_status.keys()) # イテレーション中の変更を避ける

            for fc2_id in ids_to_process:
                task = self.task_status.get(fc2_id)
                logging.debug(f"レジューム処理中タスク: {fc2_id} - Status: {task.get('status') if task else 'None'}, LocalPath: {task.get('local_path') if task else 'N/A'}") # デバッグログ追加
                if task and task.get("status") == "paused":
                    logging.debug(f"タスク {fc2_id} はpaused状態です。キューに戻すか判定。") # デバッグログ追加
                    # 中断されたタスクを適切なキューに戻す
                    if task.get("local_path"):
                        logging.debug(f"タスク {fc2_id} にlocal_pathがあります。アップロードキューに戻します。") # デバッグログ追加
                        # local_path があればアップロードキューに戻す
                        if fc2_id not in self.upload_queue:
                            self.upload_queue.appendleft(fc2_id) # 先頭に戻す
                            task["status"] = "pending_upload"
                            task["last_updated"] = datetime.now().isoformat()
                            resumed_ul += 1
                            logging.info(f"中断されたアップロードタスクを再開キューに追加: {fc2_id}") # ログ維持
                            logging.debug(f"タスク {fc2_id} をアップロードキューに追加しました。") # デバッグログ追加
                        else:
                            logging.debug(f"タスク {fc2_id} は既にアップロードキューに存在します。状態をpending_uploadに更新。") # デバッグログ維持
                            task["status"] = "pending_upload" # 状態だけ更新
                            task["last_updated"] = datetime.now().isoformat()
                    else:
                        logging.debug(f"タスク {fc2_id} にlocal_pathがありません。ダウンロードキューに戻します。") # デバッグログ追加
                        # local_path がなければダウンロードキューに戻す
                        if fc2_id not in self.download_queue:
                            self.download_queue.appendleft(fc2_id) # 先頭に戻す
                            task["status"] = "pending_download"
                            task["last_updated"] = datetime.now().isoformat()
                            resumed_dl += 1
                            logging.info(f"中断されたダウンロードタスクを再開キューに追加: {fc2_id}") # ログ維持
                            logging.debug(f"タスク {fc2_id} をダウンロードキューに追加しました。") # デバッグログ追加
                        else:
                            logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。状態をpending_downloadに更新。") # デバッグログ維持
                            task["status"] = "pending_download" # 状態だけ更新
                            task["last_updated"] = datetime.now().isoformat()
                elif task:
                     logging.debug(f"タスク {fc2_id} はpaused状態ではありません ({task.get('status')})。レジューム処理スキップ。") # デバッグログ維持
                else:
                     logging.warning(f"タスク {fc2_id} がtask_statusに見つかりません。") # ログ維持

            if resumed_dl > 0 or resumed_ul > 0:
                logging.info(f"{resumed_dl}件のダウンロード、{resumed_ul}件のアップロードを再開キューに追加しました。") # ログ維持
                logging.debug(f"レジューム処理後のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
                logging.debug(f"レジューム処理後のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
                logging.debug(f"レジューム処理後のupload_queue: {list(self.upload_queue)}") # デバッグログ維持
                await self._save_status()
            logging.info("中断されたタスクのレジューム処理を完了しました。") # ログ追加


    async def reset_failed_tasks(self):
        """'error', 'failed_download', 'failed_upload' 状態のタスクをリセットしてダウンロードキューに戻す"""
        async with self._lock:
            logging.debug("失敗タスクリセット処理開始。") # デバッグログ追加
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
                logging.debug(f"processed_ids から失敗タスク {fc2_id} を一時削除") # ログ維持


            for fc2_id in ids_to_process:
                task = self.task_status.get(fc2_id)
                if task and (task.get("status", "").startswith("fail") or task.get("status") == "error"):
                    logging.debug(f"タスク {fc2_id} は失敗状態です。リセット処理開始。") # デバッグログ追加
                    if fc2_id not in self.download_queue:
                        logging.debug(f"タスク {fc2_id} はダウンロードキューにありません。リセットして追加します。") # デバッグログ追加
                        # 状態をリセット
                        task["status"] = "pending_download"
                        task["download_progress"] = 0
                        task["upload_progress"] = 0
                        task["local_path"] = None
                        task["error_message"] = None
                        task["last_updated"] = datetime.now().isoformat()
                        self.download_queue.appendleft(fc2_id) # 再試行のため先頭に追加
                        reset_count += 1
                        logging.info(f"失敗したタスクをリセットし、ダウンロードキューに追加: {fc2_id}") # ログ維持
                    else:
                        logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在するため、リセットのみ行います。") # ログ維持
                        task["status"] = "pending_download"
                        task["download_progress"] = 0
                        task["upload_progress"] = 0
                        task["local_path"] = None
                        task["error_message"] = None
                        task["last_updated"] = datetime.now().isoformat()
                    logging.debug(f"タスク {fc2_id} のリセット処理完了。") # デバッグログ追加


            if reset_count > 0 or failed_ids_in_processed: # processed_ids から削除があった場合も保存
                logging.info(f"{reset_count} 件の失敗したタスクをリセットしました。") # ログ維持
                await self._save_status()
                logging.debug("失敗タスクリセット処理完了 - 状態を保存しました。") # デバッグログ追加
            else:
                logging.debug("失敗タスクリセット処理完了 - 対象タスクなし。") # デバッグログ追加


    async def check_and_resume_downloads(self, download_dir: str):
        """
        ダウンロードディレクトリをチェックし、既存ファイルに基づいてタスクをレジュームまたはエラーとしてマークする。
        部分的にダウンロードされたファイル (.part) や、対応するタスクがないファイルを処理する。
        完了したファイル (.mp4) があればアップロードキューに追加する。
        """
        async with self._lock:
            logging.info(f"ダウンロードディレクトリ '{download_dir}' をチェックし、既存ファイルに基づきタスク状態を更新します。") # ログ維持
            logging.debug(f"check_and_resume_downloads 処理開始。ディレクトリ: {download_dir}") # デバッグログ追加
            if not os.path.isdir(download_dir):
                logging.info(f"ダウンロードディレクトリ '{download_dir}' が存在しません。") # ログ維持
                logging.debug("ダウンロードディレクトリチェック処理完了 (ディレクトリなし)。") # デバッグログ追加
                return

            existing_files = [f for f in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, f))]
            logging.debug(f"ダウンロードディレクトリ内の既存ファイル: {existing_files}") # ログ維持

            processed_files = set() # 処理済みのファイル名を記録

            # .part ファイルを優先的に処理 (中断されたダウンロード)
            logging.debug(".part ファイルの処理を開始します。") # デバッグログ追加
            for filename in existing_files:
                if filename.endswith(".part"):
                    logging.debug(f".part ファイル検出: {filename}") # デバッグログ追加
                    original_filename = filename[:-5] # .part を取り除く
                    # ファイル名からFC2 IDを推測 (例: "FC2-PPV-XXXXXXX Title.mp4.part")
                    match = re.match(r"(FC2-PPV-\d+)", original_filename)
                    if match:
                        fc2_id = match.group(1)
                        full_path = os.path.join(download_dir, filename)
                        processed_files.add(filename)
                        logging.debug(f"FC2 ID 抽出: {fc2_id} from {filename}") # デバッグログ追加

                        if fc2_id in self.task_status:
                            task = self.task_status[fc2_id]
                            logging.debug(f"タスク {fc2_id} がtask_statusに見つかりました。現在の状態: {task.get('status')}") # デバッグログ追加
                            # 状態がダウンロード中、一時停止、エラーなどであればレジュームを試みる
                            if task.get("status") in ["downloading", "paused", "error", "failed_download"]:
                                logging.info(f"部分ファイル '{filename}' に基づきタスク {fc2_id} のレジュームを試みます。") # ログ維持
                                logging.debug(f"タスク {fc2_id} はレジューム可能な状態です。pending_downloadに更新。") # デバッグログ追加
                                # 状態を pending_download に戻し、キューの先頭に追加
                                task["status"] = "pending_download"
                                task["download_progress"] = 0 # 進捗をリセット (再開ロジックは download_video 側で実装される想定)
                                task["upload_progress"] = 0
                                task["local_path"] = full_path # 部分ファイルのパスを設定
                                task["error_message"] = None
                                task["last_updated"] = datetime.now().isoformat()
                                if fc2_id not in self.download_queue:
                                     self.download_queue.appendleft(fc2_id)
                                     logging.info(f"タスク {fc2_id} をダウンロードキューの先頭に追加しました。") # ログ維持
                                     logging.debug(f"タスク {fc2_id} をダウンロードキューに追加しました。") # デバッグログ追加
                                else:
                                     logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。") # ログ維持
                                logging.debug(f"タスク {fc2_id} の状態をpending_downloadに更新しました。") # デバッグログ追加
                            else:
                                logging.warning(f"部分ファイル '{filename}' に対応するタスク {fc2_id} はレジューム不可能な状態 '{task.get('status')}' です。ファイルを削除します。") # ログ維持
                                try:
                                    os.remove(full_path)
                                    logging.info(f"部分ファイル '{full_path}' を削除しました。") # ログ維持
                                except OSError as e:
                                    logging.error(f"部分ファイル '{full_path}' の削除に失敗しました: {e}") # ログ維持
                                logging.debug(f"タスク {fc2_id} はレジューム不可。ファイル削除処理完了。") # デバッグログ追加
                        else:
                            logging.warning(f"部分ファイル '{filename}' に対応するタスク {fc2_id} が task_status に見つかりません。ファイルを削除します。") # ログ維持
                            try:
                                os.remove(full_path)
                                logging.info(f"部分ファイル '{full_path}' を削除しました。") # ログ維持
                            except OSError as e:
                                logging.error(f"部分ファイル '{full_path}' の削除に失敗しました: {e}") # ログ維持
                            logging.debug(f"タスク {fc2_id} 見つからず。ファイル削除処理完了。") # デバッグログ追加
                    else:
                        logging.warning(f"部分ファイル '{filename}' からFC2 IDを抽出できませんでした。ファイルを削除します。") # ログ維持
                        try:
                            os.remove(os.path.join(download_dir, filename))
                            logging.info(f"部分ファイル '{os.path.join(download_dir, filename)}' を削除しました。") # ログ維持
                        except OSError as e:
                            logging.error(f"部分ファイル '{os.path.join(download_dir, filename)}' の削除に失敗しました: {e}") # ログ維持
                        logging.debug(f"ファイル {filename} からID抽出失敗。ファイル削除処理完了。") # デバッグログ追加
            logging.debug(".part ファイルの処理を完了しました。") # デバッグログ追加


            # .part 以外のファイルを処理 (完了したファイルまたは孤立したファイル)
            logging.debug(".part 以外のファイルの処理を開始します。") # デバッグログ追加
            for filename in existing_files:
                 if filename not in processed_files: # .part ファイルは既に処理済み
                    logging.debug(f".part 以外のファイル検出: {filename}") # デバッグログ追加
                    # ファイル名からFC2 IDを推測
                    match = re.match(r"(FC2-PPV-\d+)", filename)
                    if match:
                        fc2_id = match.group(1)
                        full_path = os.path.join(download_dir, filename)
                        logging.debug(f"FC2 ID 抽出: {fc2_id} from {filename}") # デバッグログ追加

                        if fc2_id in self.task_status:
                            task = self.task_status[fc2_id]
                            logging.debug(f"タスク {fc2_id} がtask_statusに見つかりました。現在の状態: {task.get('status')}") # デバッグログ追加
                            # .mp4 ファイルで、タスクが pending_download または downloading の場合 -> アップロードキューへ
                            if filename.lower().endswith(".mp4") and task.get("status") in ["pending_download", "downloading"]:
                                logging.info(f"完了ファイル '{filename}' に対応するタスク {fc2_id} をアップロードキューに追加します。") # ログ維持
                                logging.debug(f"タスク {fc2_id} はpending_download/downloading状態の.mp4ファイルです。pending_uploadに更新。") # デバッグログ追加
                                task["status"] = "pending_upload"
                                task["download_progress"] = 100.0 # ダウンロードは完了
                                task["upload_progress"] = 0
                                task["local_path"] = full_path # ローカルパスを設定
                                task["error_message"] = None
                                task["last_updated"] = datetime.now().isoformat()
                                if fc2_id not in self.upload_queue:
                                     self.upload_queue.append(fc2_id) # アップロードキューの最後に追加
                                     logging.info(f"タスク {fc2_id} をアップロードキューに追加しました。") # ログ維持
                                     logging.debug(f"タスク {fc2_id} をアップロードキューに追加しました。") # デバッグログ追加
                                else:
                                     logging.debug(f"タスク {fc2_id} は既にアップロードキューに存在します。") # ログ維持
                                logging.debug(f"タスク {fc2_id} の状態をpending_uploadに更新しました。") # デバッグログ追加

                            # pending_download のままファイルが存在するのはおかしいのでエラーとする (mp4 以外)
                            elif task.get("status") == "pending_download":
                                logging.warning(f"ファイル '{filename}' に対応するタスク {fc2_id} が pending_download 状態です。ファイルが不完全か孤立している可能性があります。ファイルを削除し、タスクをリセットします。") # ログ維持
                                logging.debug(f"タスク {fc2_id} はpending_download状態の孤立ファイルです。リセット処理開始。") # デバッグログ追加
                                try:
                                    os.remove(full_path)
                                    logging.info(f"ファイル '{full_path}' を削除しました。") # ログ維持
                                except OSError as e:
                                    logging.error(f"ファイル '{full_path}' の削除に失敗しました: {e}") # ログ維持
                                # タスクをリセットしてダウンロードキューに戻す
                                if fc2_id not in self.download_queue:
                                     task["status"] = "pending_download"
                                     task["download_progress"] = 0
                                     task["upload_progress"] = 0
                                     task["local_path"] = None
                                     task["error_message"] = "孤立ファイル削除によるリセット"
                                     task["last_updated"] = datetime.now().isoformat()
                                     self.download_queue.appendleft(fc2_id)
                                     logging.info(f"タスク {fc2_id} をダウンロードキューに追加しました。") # ログ維持
                                     logging.debug(f"タスク {fc2_id} をダウンロードキューに追加しました。") # デバッグログ追加
                                else:
                                     logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。リセットのみ行います。") # デバッグログ追加
                                     task["status"] = "pending_download"
                                     task["download_progress"] = 0
                                     task["upload_progress"] = 0
                                     task["local_path"] = None
                                     task["error_message"] = "孤立ファイル削除によるリセット"
                                     task["last_updated"] = datetime.now().isoformat()
                                logging.debug(f"タスク {fc2_id} の状態をpending_downloadにリセットしました。") # デバッグログ追加

                            else:
                                logging.debug(f"ファイル '{filename}' に対応するタスク {fc2_id} は他の状態 ({task.get('status')}) です。処理スキップ。") # デバッグログ追加

                        else:
                            logging.warning(f"ファイル '{filename}' に対応するタスク {fc2_id} が task_status に見つかりません。ファイルを削除します。") # ログ維持
                            try:
                                os.remove(full_path)
                                logging.info(f"ファイル '{full_path}' を削除しました。") # ログ維持
                            except OSError as e:
                                logging.error(f"ファイル '{full_path}' の削除に失敗しました: {e}") # ログ維持
                            logging.debug(f"タスク {fc2_id} 見つからず。ファイル削除処理完了。") # デバッグログ追加
                    else:
                        logging.warning(f"ファイル '{filename}' からFC2 IDを抽出できませんでした。ファイルを削除します。") # ログ維持
                        try:
                            os.remove(os.path.join(download_dir, filename))
                            logging.info(f"ファイル '{os.path.join(download_dir, filename)}' を削除しました。") # ログ維持
                        except OSError as e:
                            logging.error(f"ファイル '{os.path.join(download_dir, filename)}' の削除に失敗しました: {e}") # ログ維持
                        logging.debug(f"ファイル {filename} からID抽出失敗。ファイル削除処理完了。") # デバッグログ追加
            logging.debug(".part 以外のファイルの処理を完了しました。") # デバッグログ追加

            # check_and_resume_downloads 処理完了後に状態を保存
            await self._save_status()
            logging.info("ダウンロードディレクトリのチェックとタスク状態の更新を完了しました。") # ログ追加
            logging.debug("check_and_resume_downloads 処理完了。") # デバッグログ追加


    async def delete_local_file(self, fc2_id: str):
        """指定されたタスクに関連するローカルファイルを削除する"""
        async with self._lock:
            logging.debug(f"ローカルファイル削除処理開始: {fc2_id}") # デバッグログ追加
            task = self.task_status.get(fc2_id)
            if task and task.get("local_path"):
                local_path = task["local_path"]
                if os.path.exists(local_path):
                    try:
                        os.remove(local_path)
                        logging.info(f"ローカルファイルを削除しました: {local_path}") # ログ維持
                        # 状態からローカルパスを削除
                        task["local_path"] = None
                        task["last_updated"] = datetime.now().isoformat()
                        await self._save_status()
                        logging.debug(f"ローカルファイル {local_path} を削除し、状態を保存しました。") # デバッグログ追加
                    except OSError as e:
                        logging.error(f"ローカルファイルの削除に失敗しました: {local_path} - {e}") # ログ維持
                        task["error_message"] = f"ファイル削除失敗: {e}"
                        task["last_updated"] = datetime.now().isoformat()
                        await self._save_status()
                        logging.debug(f"ローカルファイル {local_path} の削除に失敗し、状態を保存しました。") # デバッグログ追加
                else:
                    logging.warning(f"削除対象のローカルファイルが見つかりません: {local_path}") # ログ維持
                    # ファイルがない場合でも状態からパスを削除するか？
                    task["local_path"] = None
                    task["last_updated"] = datetime.now().isoformat()
                    await self._save_status()
                    logging.debug(f"削除対象ファイル {local_path} が見つかりませんでしたが、状態からパスを削除しました。") # デバッグログ追加
            else:
                logging.warning(f"ローカルファイル削除対象のタスクが見つからないか、ローカルパスが設定されていません: {fc2_id}") # ログ維持
                logging.debug(f"ローカルファイル削除処理完了: {fc2_id} - 対象なし。") # デバッグログ追加