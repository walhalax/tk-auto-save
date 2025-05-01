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

        # 状態更新通知のためのイベント
        self._status_updated_event = asyncio.Event()

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
            self._status_updated_event.set() # 読み込み完了時にもイベントをセット

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
        self._status_updated_event.set() # 保存完了時にもイベントをセット


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
        self._status_updated_event.set() # リセット完了時にもイベントをセット


    async def add_download_task(self, video_info: Dict[str, Any]):
        """新しいダウンロードタスクをキューとステータスに追加する"""
        fc2_id = video_info.get('fc2_id')
        if not fc2_id:
            logging.warning("FC2 ID がないためタスクを追加できません。") # ログ維持
            return

        async with self._lock:
            logging.debug(f"ダウンロードタスク追加処理開始: {fc2_id}") # デバッグログ追加

            # ファイル名を推測 (download_module のロジックに合わせる)
            title = video_info.get('title', fc2_id)
            safe_filename = "".join(c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in title)
            if not safe_filename.lower().endswith('.mp4'):
                 safe_filename += '.mp4'

            # アップロード先のフォルダパスを生成 (FC2 IDの左から3桁を抜き出し、末尾を0にするルール)
            # FC2-PPV-XXX の XXX 部分を抜き出し、末尾を0にする
            match = re.search(r'FC2-PPV-(\d+)', fc2_id)
            upload_folder_name = None
            if match:
                numeric_id = match.group(1)
                if len(numeric_id) >= 3:
                    upload_folder_suffix = numeric_id[:3] # 左から3桁を抜き出し
                    # 抜き出した3桁の末尾を0にする
                    if len(upload_folder_suffix) > 0:
                         upload_folder_suffix = upload_folder_suffix[:-1] + '0'
                    else:
                         upload_folder_suffix = '0' # 3桁未満の場合の考慮（念のため）

                    upload_folder_name = f"FC2-PPV-{upload_folder_suffix}"
                elif len(numeric_id) > 0:
                     # 3桁未満だが数字がある場合、その数字の末尾を0にする
                     upload_folder_suffix = numeric_id[:-1] + '0'
                     upload_folder_name = f"FC2-PPV-{upload_folder_suffix}"
                else:
                    # 数字部分がない場合はデフォルトのフォルダ名など考慮が必要かもしれません
                    upload_folder_name = "FC2-PPV-0"
            else:
                 # FC2-PPV-XXX 形式でない場合は、FC2 ID そのものを使用し末尾を0にする（前回のロジックを維持）
                 if len(fc2_id) > 0:
                      upload_folder_suffix = fc2_id[:-1] + '0'
                      upload_folder_name = f"FC2-PPV-{upload_folder_suffix}"
                 else:
                      upload_folder_name = "FC2-PPV-0"


            upload_dir = os.path.join("uploads", upload_folder_name)
            upload_path = os.path.join(upload_dir, safe_filename)

            # アップロード先に同名のファイルが既に存在し、かつサイズが0より大きいかチェック (容量100%とみなす)
            if os.path.exists(upload_path) and os.path.getsize(upload_path) > 0:
                logging.info(f"アップロード先に既存の完全なファイル '{upload_path}' を検出。ダウンロードをスキップし、ダウンロード完了としてマーク、アップロードキューに追加します。") # ログ維持

                # タスクが task_status に存在しない場合は新しく作成
                if fc2_id not in self.task_status:
                     self.task_status[fc2_id] = {
                         "title": title,
                         "url": video_info.get('url'), # 元のURLは保持
                         "added_date": video_info.get('added_date_str'),
                         "rating": video_info.get('rating'),
                         "upload_progress": 0,
                         "error_message": None,
                     }

                # タスクの状態を completed に設定し、ローカルパスとダウンロード進捗を更新
                self.task_status[fc2_id].update({
                    "status": "completed", # ダウンロード完了としてマーク
                    "download_progress": 100.0,
                    "local_path": upload_path, # アップロード先のパスを設定
                    "last_updated": datetime.now().isoformat()
                })

                # processed_ids に含まれている場合は削除 (再度処理させるため)
                if fc2_id in self.processed_ids:
                    self.processed_ids.remove(fc2_id)
                    logging.debug(f"タスク {fc2_id} をprocessed_idsから削除しました。") # デバッグログ追加

                # アップロードキューに存在しない場合のみ追加
                if fc2_id not in self.upload_queue:
                    self.upload_queue.append(fc2_id)
                    logging.info(f"アップロードキューに追加: {fc2_id} - {title}") # ログ維持
                else:
                    logging.debug(f"タスク {fc2_id} は既にアップロードキューに存在します。") # デバッグログ維持

                await self._save_status() # 状態を保存
                logging.debug(f"タスク {fc2_id} をダウンロード完了としてマークし、アップロードキューに追加しました。状態を保存。") # デバッグログ追加
                self._status_updated_event.set() # 状態変更時にイベントをセット
                return # 処理終了

            # アップロード先に完全なファイルがない場合、ローカルのdownloadsフォルダに既存ファイルがあるかチェック
            local_downloads_path = os.path.join("downloads", safe_filename)
            if os.path.exists(local_downloads_path) and os.path.getsize(local_downloads_path) > 0:
                # ファイル名からFC2 IDを抽出して、タスクの状態を確認
                extracted_fc2_id = self._extract_fc2_id_from_filename(safe_filename)
                if extracted_fc2_id == fc2_id:
                    task = self.task_status.get(fc2_id)
                    # タスクが存在し、かつダウンロード完了、アップロード待ち、アップロード中、スキップアップロードの状態であればスキップ
                    if task and task.get("status") in ["completed", "pending_upload", "uploading", "skipped_upload"]:
                        logging.info(f"ローカルに既存ファイル '{local_downloads_path}' を検出。タスク {fc2_id} は既に処理済みまたは処理中のためスキップします。") # ログ維持
                        logging.debug(f"タスク {fc2_id} は状態 '{task.get('status')}' で既に存在するためスキップ。") # デバッグログ追加
                        self._status_updated_event.set() # 状態変更時にイベントをセット
                        return # 処理終了
                    elif task and task.get("status") in ["pending_download", "downloading", "paused", "error", "failed_download", "failed_upload"]:
                         # ファイルは存在するが、タスクの状態がダウンロード中やエラーなどの場合
                         logging.warning(f"ローカルに既存ファイル '{local_downloads_path}' を検出しましたが、タスク {fc2_id} の状態が '{task.get('status')}' です。タスクをリセットしてダウンロードキューに戻します。") # ログ維持
                         # タスクをリセットしてダウンロードキューに戻す処理は check_and_resume_downloads で行うため、ここでは何もしない
                         pass # check_and_resume_downloads に任せる
                    else:
                         # タスクが task_status に存在しない場合
                         logging.info(f"ローカルに既存ファイル '{local_downloads_path}' を検出。タスク {fc2_id} が task_status に存在しないため、ダウンロード完了としてマークし、アップロードキューに追加します。") # ログ維持
                         # タスクを新しく作成し、ダウンロード完了としてマーク
                         self.task_status[fc2_id] = {
                             "status": "completed", # ダウンロード完了としてマーク
                             "title": title,
                             "url": video_info.get('url'), # 元のURLは保持
                             "added_date": video_info.get('added_date_str'),
                             "rating": video_info.get('rating'),
                             "download_progress": 100.0,
                             "upload_progress": 0,
                             "local_path": local_downloads_path, # 既存のローカルパスを設定
                             "error_message": None,
                             "last_updated": datetime.now().isoformat()
                         }
                         # processed_ids に含まれている場合は削除 (再度処理させるため)
                         if fc2_id in self.processed_ids:
                             self.processed_ids.remove(fc2_id)
                             logging.debug(f"タスク {fc2_id} をprocessed_idsから削除しました。") # デバッグログ追加

                         # アップロードキューに存在しない場合のみ追加
                         if fc2_id not in self.upload_queue:
                             self.upload_queue.append(fc2_id)
                             logging.info(f"アップロードキューに追加: {fc2_id} - {title}") # ログ維持
                         else:
                             logging.debug(f"タスク {fc2_id} は既にアップロードキューに存在します。") # デバッグログ維持

                         await self._save_status() # 状態を保存
                         logging.debug(f"タスク {fc2_id} をダウンロード完了としてマークし、アップロードキューに追加しました。状態を保存。") # デバッグログ追加
                         self._status_updated_event.set() # 状態変更時にイベントをセット
                         return # 処理終了

                else:
                    logging.warning(f"ローカルに既存ファイル '{local_downloads_path}' を検出しましたが、ファイル名からFC2 ID '{fc2_id}' を抽出できませんでした。スキップせず、ダウンロードタスクとして追加/更新します。") # ログ維持
                    # FC2 IDが一致しない場合は、既存ファイルと見なさず、ダウンロードタスクとして続行


            # ローカルファイルもアップロード先ファイルも存在しない、またはサイズが0
            # タスクが task_status に存在しない、または状態が pending_download/downloading でない場合
            if fc2_id not in self.task_status or (self.task_status[fc2_id].get("status") not in ["pending_download", "downloading"]):
                logging.info(f"タスク {fc2_id} をダウンロードキューに追加/更新します。") # ログ維持
                self.task_status[fc2_id] = {
                    "status": "pending_download",
                    "title": title,
                    "url": video_info.get('url'),
                    "added_date": video_info.get('added_date_str'),
                    "rating": video_info.get('rating'),
                    "download_progress": 0,
                    "upload_progress": 0,
                    "local_path": None, # 新規ダウンロードの場合はローカルパスをリセット
                    "error_message": None,
                    "last_updated": datetime.now().isoformat() # ここで datetime を使用
                }
                # processed_ids に含まれている場合は削除
                if fc2_id in self.processed_ids:
                    self.processed_ids.remove(fc2_id)
                    logging.debug(f"タスク {fc2_id} をprocessed_idsから削除しました。") # デバッグログ追加

                # ダウンロードキューに存在しない場合のみ追加
                if fc2_id not in self.download_queue:
                    self.download_queue.append(fc2_id)
                    logging.info(f"ダウンロードキューに追加: {fc2_id} - {title}") # ログ維持
                else:
                    logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。スキップ。") # デバッグログ維持

                await self._save_status() # 状態を保存
                logging.debug(f"タスク {fc2_id} をダウンロードキューに追加/更新し、状態を保存しました。") # デバッグログ追加
            else:
                logging.debug(f"タスク {fc2_id} は既にダウンロード待ちまたはダウンロード中です。スキップ。") # デバッグログ維持
            logging.debug(f"ダウンロードタスク追加処理完了: {fc2_id}") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
                logging.debug(f"進捗更新対象のタスクが見つかりません: {fc2_id}") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
                logging.debug(f"ローカルパス設定対象のタスクが見つかりません: {fc2_id}") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
                logging.debug(f"進捗更新対象のタスクが見つかりません: {fc2_id}") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
                elif status == "completed" or status == "skipped_upload": # skipped_upload も完了扱い
                     # 完了/スキップの場合は100%または0%など、適切な値を設定
                     task_info["progress"] = 100.0 if status == "completed" or status == "skipped_upload" else 0.0
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
                 elif status == "completed" or status == "skipped_upload": # skipped_upload も完了扱い
                      task_copy["progress"] = 100.0 if status == "completed" or status == "skipped_upload" else 0.0
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
        self._status_updated_event.set() # 状態変更時にイベントをセット


    async def clear_stop_request(self):
        """停止リクエストフラグをクリアする"""
        async with self._lock:
            logging.debug("停止リクエストクリア処理開始。") # デバッグログ追加
            self.stop_requested = False
            logging.info("停止リクエストをクリアしました。") # ログ維持
            logging.debug("停止リクエストクリア処理完了。") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


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
                            logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。状態のみ更新。") # デバッグログ維持
                            task["status"] = "pending_download" # 状態だけ更新
                            task["last_updated"] = datetime.now().isoformat()

            logging.info(f"中断されたタスクのレジューム処理が完了しました。ダウンロード: {resumed_dl}件, アップロード: {resumed_ul}件") # ログ維持
            logging.debug(f"レジューム処理完了時のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
            logging.debug(f"レジューム処理完了時のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
            logging.debug(f"レジューム処理完了時のupload_queue: {list(self.upload_queue)}") # デバッグログ維持
            await self._save_status() # 状態を保存
            logging.debug("中断されたタスクのレジューム処理完了。状態を保存しました。") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


    async def reset_failed_tasks(self):
        """'error', 'failed_download', 'failed_upload' 状態のタスクをリセットしてダウンロードキューに戻す"""
        async with self._lock:
            logging.debug("失敗タスクリセット処理開始。") # デバッグログ追加
            failed_statuses = ["error", "failed_download", "failed_upload"]
            ids_to_reset = [fc2_id for fc2_id, task in self.task_status.items() if task.get("status") in failed_statuses]
            logging.debug(f"リセット対象の失敗タスクID: {ids_to_reset}") # デバッグログ追加

            # processed_ids に含まれている失敗タスクIDを削除
            failed_ids_in_processed = [fc2_id for fc2_id in ids_to_reset if fc2_id in self.processed_ids]
            for fc2_id in failed_ids_in_processed:
                 self.processed_ids.remove(fc2_id)
                 logging.debug(f"失敗タスク {fc2_id} をprocessed_idsから削除しました。") # デバッグログ追加


            reset_count = 0
            for fc2_id in ids_to_reset:
                task = self.task_status[fc2_id]
                logging.info(f"失敗タスクをリセットします: {fc2_id} (現在の状態: {task.get('status')})") # ログ維持
                # 状態を pending_download に戻し、進捗とエラーメッセージをリセット
                task.update({
                    "status": "pending_download",
                    "download_progress": 0,
                    "upload_progress": 0, # アップロード失敗の場合もダウンロードからやり直し
                    "local_path": None, # ローカルファイルは削除される想定 (check_and_resume_downloads で処理)
                    "error_message": None,
                    "last_updated": datetime.now().isoformat()
                })
                # ダウンロードキューに存在しない場合のみ追加
                if fc2_id not in self.download_queue:
                    self.download_queue.appendleft(fc2_id) # 先頭に追加して優先的に処理
                    logging.info(f"失敗タスク {fc2_id} をダウンロードキューに戻しました。") # ログ維持
                    reset_count += 1
                else:
                    logging.debug(f"失敗タスク {fc2_id} は既にダウンロードキューに存在します。状態のみ更新。") # デバッグログ維持

            if reset_count > 0:
                logging.info(f"失敗タスク {reset_count} 件をリセットし、ダウンロードキューに戻しました。") # ログ維持
                await self._save_status() # 状態を保存
                logging.debug("失敗タスクリセット処理完了。状態を保存しました。") # デバッグログ追加
            else:
                logging.info("リセット対象の失敗タスクはありませんでした。") # ログ維持
                logging.debug("失敗タスクリセット処理完了 (対象なし)。") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット

    def _extract_fc2_id_from_filename(self, filename: str) -> Optional[str]:
        """ファイル名からFC2 IDを抽出する"""
        # download_module のファイル名生成ロジックに合わせた正規表現を使用
        # 例: FC2-PPV-1234567_タイトル.mp4 のような形式を想定
        match = re.search(r'FC2-PPV-(\d+)', filename)
        if match:
            return match.group(1)
        return None


    async def check_and_resume_downloads(self, download_dir: str):
        """
        ダウンロードディレクトリをスキャンし、既存のダウンロード済みファイルや
        中断された可能性のある部分ファイルをチェックして、必要に応じてタスクをレジュームまたはリセットする。
        また、アップロード完了済みのタスクに対応する部分ファイルを削除する。
        """
        async with self._lock:
            logging.info(f"ダウンロードディレクトリ '{download_dir}' のスキャンを開始します。") # ログ維持
            logging.debug(f"スキャン開始時のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
            logging.debug(f"スキャン開始時のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
            logging.debug(f"スキャン開始時のupload_queue: {list(self.upload_queue)}") # デバッグログ維持

            if not os.path.isdir(download_dir):
                logging.warning(f"ダウンロードディレクトリ '{download_dir}' が見つかりません。スキップします。") # ログ維持
                logging.debug("ダウンロードディレクトリのスキャン処理完了 (ディレクトリなし)。") # デバッグログ追加
                return

            # ディレクトリ内のファイルとディレクトリをリストアップ
            try:
                entries = os.listdir(download_dir)
                logging.debug(f"ディレクトリ '{download_dir}' の内容: {entries}") # デバッグログ追加
            except OSError as e:
                logging.error(f"ダウンロードディレクトリ '{download_dir}' の読み取りに失敗しました: {e}") # ログ維持
                logging.debug("ダウンロードディレクトリのスキャン処理完了 (読み取りエラー)。") # デバッグログ追加
                return

            files_in_dir = [entry for entry in entries if os.path.isfile(os.path.join(download_dir, entry))]
            logging.debug(f"ディレクトリ内のファイル: {files_in_dir}") # デバッグログ追加

            # 既存のダウンロード済みファイル (.mp4) をチェック
            for filename in files_in_dir:
                if filename.lower().endswith('.mp4'):
                    file_path = os.path.join(download_dir, filename)
                    logging.debug(f".mp4 ファイルを検出: {file_path}") # デバッグログ追加
                    fc2_id = self._extract_fc2_id_from_filename(filename)
                    if fc2_id:
                        logging.debug(f"ファイル名 '{filename}' からFC2 ID '{fc2_id}' を抽出しました。") # デバッグログ追加
                        # task_status に存在し、かつダウンロード完了/アップロード待ち/アップロード中/完了/スキップアップロードの状態でない場合
                        # または task_status に存在しない場合
                        task = self.task_status.get(fc2_id)
                        logging.debug(f"タスク {fc2_id} の現在の状態: {task.get('status') if task else 'None'}") # デバッグログ追加
                        if not task or task.get("status") not in ["completed", "pending_upload", "uploading", "skipped_upload"]:
                             logging.info(f"既存のダウンロード済みファイル '{filename}' に対応するタスク {fc2_id} を検出。アップロードキューに追加します。") # ログ維持
                             # タスクが task_status に存在しない場合は新しく作成
                             if not task:
                                  self.task_status[fc2_id] = {
                                      "title": filename, # タイトルはファイル名から推測
                                      "url": None, # 元のURLは不明
                                      "added_date": datetime.now().isoformat(),
                                      "rating": None,
                                      "download_progress": 100.0,
                                      "upload_progress": 0,
                                      "error_message": None,
                                  }
                                  task = self.task_status[fc2_id] # 新しく作成したタスクを取得
                                  logging.debug(f"タスク {fc2_id} を新しく作成しました。") # デバッグログ追加

                             # タスクの状態を completed に設定し、ローカルパスとダウンロード進捗を更新
                             task.update({
                                 "status": "completed", # ダウンロード完了としてマーク
                                 "download_progress": 100.0,
                                 "local_path": file_path, # 既存のローカルパスを設定
                                 "last_updated": datetime.now().isoformat()
                             })

                             # processed_ids に含まれている場合は削除 (再度処理させるため)
                             if fc2_id in self.processed_ids:
                                 self.processed_ids.remove(fc2_id)
                                 logging.debug(f"タスク {fc2_id} をprocessed_idsから削除しました。") # デバッグログ追加

                             # アップロードキューに存在しない場合のみ追加
                             if fc2_id not in self.upload_queue:
                                 self.upload_queue.append(fc2_id)
                                 logging.info(f"アップロードキューに追加: {fc2_id} - {filename}") # ログ維持
                                 logging.debug(f"タスク {fc2_id} をアップロードキューに追加しました。") # デバッグログ追加
                             else:
                                 logging.debug(f"タスク {fc2_id} は既にアップロードキューに存在します。") # デバッグログ維持

                        else:
                             logging.debug(f"ファイル '{filename}' に対応するタスク {fc2_id} は既に処理済みまたは処理中です (状態: {task.get('status')})。スキップ。") # デバッグログ追加
                    else:
                        logging.warning(f"ファイル名 '{filename}' からFC2 IDを抽出できませんでした。スキップします。") # ログ維持
                        logging.debug(f"ファイル '{filename}' のFC2 ID抽出に失敗しました。") # デバッグログ追加

            # 部分ファイル (.part) をチェック (yt-dlp の一時ファイル)
            for filename in files_in_dir:
                if filename.lower().endswith('.part'):
                    file_path = os.path.join(download_dir, filename)
                    logging.debug(f".part ファイルを検出: {file_path}") # デバッグログ追加
                    # .part ファイル名から元のファイル名を推測し、そこからFC2 IDを抽出
                    # 例: タイトル.mp4.part -> タイトル.mp4 -> FC2-PPV-1234567
                    original_filename = filename[:-5] # '.part' を削除
                    fc2_id = self._extract_fc2_id_from_filename(original_filename)

                    if fc2_id:
                        logging.debug(f"部分ファイル '{filename}' からFC2 ID '{fc2_id}' を抽出しました。") # デバッグログ追加
                        task = self.task_status.get(fc2_id)
                        logging.debug(f"タスク {fc2_id} の現在の状態: {task.get('status') if task else 'None'}") # デバッグログ追加

                        # タスクが存在し、かつアップロード完了済みの状態であれば部分ファイルを削除
                        if task and task.get("status") in ["completed", "skipped_upload"]:
                             logging.info(f"アップロード完了済みのタスク {fc2_id} に対応する部分ファイル '{filename}' を検出。ファイルを削除します。") # ログ維持
                             try:
                                 os.remove(file_path)
                                 logging.info(f"部分ファイル '{file_path}' を削除しました。") # ログ維持
                                 logging.debug(f"部分ファイル '{file_path}' の削除に成功しました。") # デバッグログ追加
                             except OSError as e:
                                 logging.error(f"部分ファイル '{file_path}' の削除に失敗しました: {e}") # ログ維持
                                 logging.debug(f"部分ファイル '{file_path}' の削除に失敗しました: {e}") # デバッグログ追加
                        # task_status に存在し、かつ pending_download, downloading, paused, error, failed_download 状態の場合にレジューム可能と判断
                        elif task and task.get("status") in ["pending_download", "downloading", "paused", "error", "failed_download"]:
                            logging.info(f"中断されたダウンロードファイル '{filename}' に対応するタスク {fc2_id} を検出。ダウンロードをレジュームします。") # ログ維持
                            # 状態を pending_download に戻し、ダウンロードキューの先頭に追加
                            task["status"] = "pending_download"
                            task["last_updated"] = datetime.now().isoformat()
                            # local_path は .part ファイルのパスを設定 (yt-dlp が認識するため)
                            task["local_path"] = file_path # .part ファイルのパスを設定
                            if fc2_id not in self.download_queue:
                                self.download_queue.appendleft(fc2_id) # 先頭に追加して優先的に処理
                                logging.info(f"中断されたダウンロードタスク {fc2_id} をダウンロードキューに戻しました。") # ログ維持
                                logging.debug(f"タスク {fc2_id} をダウンロードキューに追加しました。") # デバッグログ追加
                            else:
                                logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。状態のみ更新。") # デバッグログ維持

                        else:
                            # タスクが task_status に存在しない、またはレジューム・完了以外の状態の場合
                            logging.warning(f"部分ファイル '{filename}' に対応するタスク {fc2_id} はレジューム対象外の状態 '{task.get('status') if task else 'None'}' です、またはタスクが task_status に見つかりません。ファイルを削除せずスキップします。") # ログ維持
                            # ファイルを削除せずスキップ
                            pass

                    else:
                        # FC2 ID が抽出できない .part ファイルは孤立している可能性が高いので削除
                        logging.warning(f"部分ファイル '{filename}' からFC2 IDを抽出できませんでした。孤立ファイルとして削除します。") # ログ維持
                        try:
                            os.remove(file_path)
                            logging.info(f"孤立した部分ファイル '{file_path}' を削除しました。") # ログ維持
                            logging.debug(f"孤立した部分ファイル '{file_path}' の削除に成功しました。") # デバッグログ追加
                        except OSError as e:
                            logging.error(f"孤立した部分ファイル '{file_path}' の削除に失敗しました: {e}") # ログ維持
                            logging.debug(f"孤立した部分ファイル '{file_path}' の削除に失敗しました: {e}") # デバッグログ追加

            # task_status にあるが、downloads フォルダにファイルが存在しないタスクをチェック
            # これは、ファイルが手動で削除されたか、ダウンロードが開始される前に中断された場合などに発生する
            ids_to_check = list(self.task_status.keys()) # イテレーション中の変更を避ける
            for fc2_id in ids_to_check:
                 task = self.task_status.get(fc2_id)
                 if task and task.get("status") in ["pending_download", "downloading", "pending_upload", "uploading", "paused"]:
                      local_path = task.get("local_path")
                      # local_path が設定されている場合のみファイル存在チェック
                      if local_path and os.path.exists(local_path):
                           logging.debug(f"タスク {fc2_id}: local_path '{local_path}' が存在します。") # デバッグログ追加
                           pass # ファイルが存在するので問題なし
                      else:
                           # ファイルが存在しない場合、タスクの状態に応じて処理
                           logging.warning(f"タスク {fc2_id} に対応するファイル '{local_path}' が見つかりません。状態: {task.get('status')}") # ログ維持
                           if task.get("status") in ["pending_download", "downloading", "paused"]:
                                # ダウンロード関連の状態の場合、タスクをリセットしてダウンロードキューに戻す
                                logging.info(f"タスク {fc2_id} (状態: {task.get('status')}) に対応するファイルが見つからないため、タスクをリセットしてダウンロードキューに戻します。") # ログ維持
                                task.update({
                                    "status": "pending_download",
                                    "download_progress": 0,
                                    "upload_progress": 0,
                                    "local_path": None, # ローカルパスをリセット
                                    "error_message": "ファイルが見つからないためリセット",
                                    "last_updated": datetime.now().isoformat()
                                })
                                if fc2_id not in self.download_queue:
                                     self.download_queue.appendleft(fc2_id) # 先頭に追加
                                     logging.debug(f"タスク {fc2_id} をダウンロードキューに追加しました。") # デバッグログ追加
                                else:
                                     logging.debug(f"タスク {fc2_id} は既にダウンロードキューに存在します。状態のみ更新。") # デバッグログ維持
                           elif task.get("status") in ["pending_upload", "uploading"]:
                                # アップロード関連の状態の場合、エラーとしてマーク
                                logging.error(f"タスク {fc2_id} (状態: {task.get('status')}) に対応するファイルが見つからないため、エラーとしてマークします。") # ログ維持
                                task.update({
                                    "status": "error",
                                    "error_message": "アップロード対象ファイルが見つかりません",
                                    "last_updated": datetime.now().isoformat()
                                })
                                # アップロードキューから削除 (もしあれば)
                                if fc2_id in self.upload_queue:
                                     self.upload_queue.remove(fc2_id)
                                     logging.debug(f"タスク {fc2_id} をアップロードキューから削除しました。") # デバッグログ追加
                                # processed_ids には追加しない (リセット可能にするため)
                                logging.debug(f"タスク {fc2_id} をprocessed_idsに追加しません。") # デバッグログ追加


            logging.info(f"ダウンロードディレクトリ '{download_dir}' のスキャンが完了しました。") # ログ維持
            logging.debug(f"スキャン完了時のtask_status: {json.dumps(self.task_status, indent=2)}") # デバッグログ維持
            logging.debug(f"スキャン完了時のdownload_queue: {list(self.download_queue)}") # デバッグログ維持
            logging.debug(f"スキャン完了時のupload_queue: {list(self.upload_queue)}") # デバッグログ維持
            await self._save_status() # 状態を保存
            logging.debug("ダウンロードディレクトリのスキャン処理完了。状態を保存しました。") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


    async def delete_local_file(self, fc2_id: str):
        """指定されたタスクに関連するローカルファイルを削除する"""
        async with self._lock:
            logging.debug(f"ローカルファイル削除処理開始: {fc2_id}") # デバッグログ追加
            task = self.task_status.get(fc2_id)
            if task and task.get("local_path"):
                local_path = task["local_path"]
                logging.debug(f"削除対象ファイル: {local_path}") # デバッグログ追加
                if os.path.exists(local_path):
                    try:
                        os.remove(local_path)
                        logging.info(f"ローカルファイル '{local_path}' を削除しました。") # ログ維持
                        # task_status から local_path を削除
                        del task["local_path"]
                        task["last_updated"] = datetime.now().isoformat()
                        await self._save_status()
                        logging.debug(f"ローカルファイル削除処理完了: {fc2_id} - ファイル削除成功、状態保存。") # デバッグログ追加
                    except OSError as e:
                        logging.error(f"ローカルファイル '{local_path}' の削除に失敗しました: {e}") # ログ維持
                        # エラーメッセージを更新
                        task["error_message"] = f"ファイル削除失敗: {e}"
                        task["last_updated"] = datetime.now().isoformat()
                        await self._save_status()
                        logging.debug(f"ローカルファイル削除処理完了: {fc2_id} - ファイル削除失敗、状態保存。") # デバッグログ追加
                else:
                    logging.warning(f"削除対象のローカルファイル '{local_path}' が見つかりません: {fc2_id}") # ログ維持
                    # ファイルが見つからない場合も task_status から local_path を削除
                    del task["local_path"]
                    task["last_updated"] = datetime.now().isoformat()
                    await self._save_status()
                    logging.debug(f"ローカルファイル削除処理完了: {fc2_id} - ファイル見つからず、状態保存。") # デバッグログ追加
            else:
                logging.warning(f"ローカルファイル削除対象のタスクが見つからないか、local_pathが設定されていません: {fc2_id}") # ログ維持
                logging.debug(f"ローカルファイル削除対象のタスクが見つからないか、local_pathが設定されていません: {fc2_id}") # デバッグログ追加
        self._status_updated_event.set() # 状態変更時にイベントをセット


    async def wait_for_status_update(self):
        """状態が更新されるまで待機する"""
        logging.debug("状態更新イベントを待機します。") # デバッグログ追加
        await self._status_updated_event.wait()
        self._status_updated_event.clear() # イベントをクリア
        logging.debug("状態更新イベントを検出しました。") # デバッグログ追加

    async def are_all_uploads_completed(self) -> bool:
        """すべてのアップロードタスクが完了したかチェックする"""
        async with self._lock:
            logging.debug("すべてのアップロード完了チェック処理開始。") # デバッグログ追加
            # アップロードキューが空であり、かつアップロード中のタスクがないことを確認
            # task_status を見て、status が 'uploading' のタスクがないかチェック
            uploading_tasks = [
                fc2_id for fc2_id, task in self.task_status.items()
                if task.get("status") == "uploading"
            ]
            is_completed = not self.upload_queue and not uploading_tasks
            logging.debug(f"アップロードキューの数: {len(self.upload_queue)}, アップロード中のタスク数: {len(uploading_tasks)}") # デバッグログ追加
            logging.debug(f"すべてのアップロード完了チェック結果: {is_completed}") # デバッグログ追加
            return is_completed

    async def wait_for_all_uploads_completion(self):
        """すべてのアップロードタスクが完了するまで待機する"""
        logging.info("すべてのアップロードタスクの完了を待機します。") # ログ追加
        while True:
            if await self.are_all_uploads_completed():
                logging.info("すべてのアップロードタスクが完了しました。") # ログ追加
                break
            logging.debug("アップロードタスク完了待ち: アップロード中のタスクまたはキューにタスクがあります。") # デバッグログ追加
            await self.wait_for_status_update() # 状態が更新されるまで待機
            # 短時間スリープしてポーリング間隔を調整 (任意)
            await asyncio.sleep(1)
