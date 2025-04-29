import os
from ftplib import FTP

class Uploader:
    def __init__(self):
        self.ftp = None
        self.progress = 0
        self.is_uploading = False
        self.is_cancelled = False
        self.current_content = None

    def connect(self):
        try:
            self.ftp = FTP('filehub')
            self.ftp.login('admin', 'admin')
            return True
        except Exception as e:
            print(f"Connection error: {str(e)}")
            return False

    def upload(self, file_path, content):
        self.is_uploading = True
        self.is_cancelled = False
        self.current_content = content
        self.progress = 0

        save_dir = os.path.join(content['category'], content['folder'])
        remote_path = os.path.join(save_dir, os.path.basename(file_path))

        try:
            with open(file_path, 'rb') as file:
                total_size = os.path.getsize(file_path)
                chunk_size = 1024

                def progress_callback(bytes_so_far):
                    self.progress = int((bytes_so_far / total_size) * 100)
                    if self.is_cancelled:
                        raise Exception("Upload cancelled")

                self.ftp.storbinary(f'STOR {remote_path}', file, chunk_size, progress_callback)
                return True
        except Exception as e:
            print(f"Upload error: {str(e)}")
            return False
        finally:
            self.is_uploading = False

    def cancel(self):
        self.is_cancelled = True