import os
import re
import subprocess
from typing import Optional, Dict, Any

class DownloadManager:
    def __init__(self):
        self._temp_folder = "downloads"
        self.download_queue = []
        self.current_progress = 0
        self.is_downloading = False
        self.is_cancelled = False

    def add_to_queue(self, url: str):
        self.download_queue.append({"url": url, "status": "queued"})

    def download_video(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            # YouTube URLからビデオIDを抽出
            video_id = self._extract_video_id(url)
            if not video_id:
                raise ValueError("有効なYouTubeビデオIDが見つかりませんでした。")

            # 一時フォルダを作成
            os.makedirs(self._temp_folder, exist_ok=True)

            # 動画ダウンロードコマンド
            command = [
                "youtube-dl",
                f"https://www.youtube.com/watch?v={video_id}",
                "--output", f"{self._temp_folder}/%(title)s.%(ext)s",
                "--no-overwrites",
                "--embed-subs",
                "--embed-thumbnail",
                "--add-metadata",
                "--write-info-json",
                "--no-post-overwrites",
                "--merge-output-format", "mp4"
            ]

            # コマンド実行
            subprocess.run(command, check=True)

            # ダウンロード完了後の処理
            return {
                "title": f"Video_{video_id}",
                "filename": f"Video_{video_id}.mp4",
                "path": os.path.join(self._temp_folder, f"Video_{video_id}.mp4")
            }

        except Exception as e:
            print(f"ダウンロードエラー: {str(e)}")
            return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        # YouTubeの各種URL形式に対応した正規表現
        pattern = r'(?:v=|/v/|/e/|u/|embed/|/watch\?v=|/v/|/shorts/|/live/|/feature/|/user/|/c/|/channel/|/playlist?list=|/results?search_query=|/watch\?.*v=|/watch\?feature=.*v=|/watch\?v=|/watch\?list=.*v=|/watch\?index=.*v=|/watch\?v=|/watch\?v=|/watch\?v=|/watch\?v=|/watch\?v=|/watch\?v=)([\w-]{11})'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None