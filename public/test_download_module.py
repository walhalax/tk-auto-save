import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from src.download_module import DownloadManager

@pytest.fixture
def download_manager():
    return DownloadManager()

def test_download_manager_initialization(download_manager):
    assert download_manager._temp_folder == "downloads"
    assert isinstance(download_manager.download_queue, list)
    assert download_manager.current_progress == 0
    assert not download_manager.is_downloading
    assert not download_manager.is_cancelled

def test_add_to_queue(download_manager):
    url = "https://www.youtube.com/watch?v=abc123"
    download_manager.add_to_queue(url)
    assert len(download_manager.download_queue) == 1
    assert download_manager.download_queue[0]["url"] == url

def test_download_video_success(download_manager):
    url = "https://www.youtube.com/watch?v=abc123"
    result = download_manager.download_video(url)
    assert result is not None
    assert "title" in result
    assert "filename" in result
    assert "path" in result

@pytest.mark.skip(reason="未実装機能のためスキップ")
def test_download_interrupt_and_resume():
    # 暫定的にスキップ
    pass

@pytest.mark.skip(reason="未実装機能のためスキップ")
def test_download_progress_callback():
    # 暫定的にスキップ
    pass