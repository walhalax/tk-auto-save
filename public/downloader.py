import os
import time
import requests
from urllib.parse import urlparse
from upload_module import Uploader

class Downloader:
    def __init__(self):
        self.progress = 0
        self.is_downloading = False
        self.is_cancelled = False
        self.current_content = None
        self.uploader = Uploader()

    def download(self, content):
        self.is_downloading = True
        self.is_cancelled = False
        self.current_content = content
        self.progress = 0
        
        # ファイル名の作成
        file_name = f"{content['title']}.mp4"
        save_dir = os.path.join("downloads", content['category'])
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, file_name)

        # ダウンロード開始
        try:
            response = requests.get(content['url'], stream=True)
            total_size = int(response.headers.get('Content-Length', 0))
            chunk_size = 1024
            
            with open(save_path, 'wb') as file:
                for i, chunk in enumerate(response.iter_content(chunk_size)):
                    if self.is_cancelled:
                        break
                    if chunk:
                        file.write(chunk)
                        self.progress = int((i * chunk_size / total_size) * 100)
                        time.sleep(0.1)
                        if self.progress >= 100:
                            break
        except Exception as e:
            print(f"Download error: {str(e)}")
            return False

        # アップロード
        if not self.uploader.upload(save_path, content):
            return False

        self.is_downloading = False
        return not self.is_cancelled and self.progress >= 100

    def cancel(self):
        self.is_cancelled = True