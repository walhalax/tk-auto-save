import httpx
from bs4 import BeautifulSoup
import logging
import os
import asyncio
from typing import Callable, Dict, Any, Optional, Coroutine # Coroutine を追加
from urllib.parse import urljoin, urldefrag # URL解析のために追加 (urlparse, urlunparse は未使用なので削除)
import re # JavaScript解析用にインポート

# ロギング設定
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# web_app側で設定するのでここではコメントアウト or 削除しても良い
# logging.getLogger(__name__).setLevel(logging.DEBUG) # 個別モジュールでレベル設定する場合

# --- MP4 URL 抽出 ---
async def find_mp4_url(video_page_url: str) -> Optional[str]:
    """
    動画ページのURLからMP4ファイルの直接URLを見つける。
    tktube.com の構造に合わせて修正済み。
    """
    logging.info(f"動画ページからMP4 URLを検索中: {video_page_url}")
    try:
        async with httpx.AsyncClient() as client:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = await client.get(video_page_url, headers=headers, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # --- 抽出ロジック (tktube.com 向け) ---
            # JavaScript内の flashvars から抽出
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string and 'flashvars' in script.string:
                    # 正規表現で video_alt_url (HD) または video_url (SD) を抽出
                    match_hd = re.search(r"video_alt_url:\s*'([^']+)'", script.string)
                    if match_hd:
                        mp4_url_raw = match_hd.group(1)
                        mp4_url = urldefrag(mp4_url_raw).url
                        logging.info(f"JavaScript flashvars (HD) からMP4 URLを発見: {mp4_url}")
                        # 相対URLの場合は絶対URLに変換
                        return urljoin(video_page_url, mp4_url)

                    match_sd = re.search(r"video_url:\s*'([^']+)'", script.string)
                    if match_sd:
                        mp4_url_raw = match_sd.group(1)
                        mp4_url = urldefrag(mp4_url_raw).url
                        logging.info(f"JavaScript flashvars (SD) からMP4 URLを発見: {mp4_url}")
                        # 相対URLの場合は絶対URLに変換
                        return urljoin(video_page_url, mp4_url)

            logging.warning(f"動画ページからMP4 URLが見つかりませんでした: {video_page_url}")
            return None
            # --- ここまで抽出ロジック ---

    except httpx.RequestError as e:
        logging.error(f"動画ページのHTML取得中にHTTPエラーが発生しました: {video_page_url} - {e}")
        return None
    except Exception as e:
        logging.error(f"MP4 URL検索中に予期せぬエラーが発生しました: {video_page_url} - {e}", exc_info=True)
        return None


# --- 動画ダウンロード処理 ---
async def download_video(
    mp4_url: str,
    output_path: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None, # コールバックを Coroutine に変更
    chunk_size: int = 8192 # 8KB
) -> bool:
    """MP4ファイルを指定されたパスにダウンロードする"""
    logging.info(f"ダウンロード開始: {mp4_url} -> {output_path}")
    total_size = 0
    downloaded_size = 0
    start_time = asyncio.get_event_loop().time()

    # 出力ディレクトリが存在しない場合は作成
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            logging.info(f"出力ディレクトリを作成しました: {output_dir}")
        except OSError as e:
            logging.error(f"出力ディレクトリの作成に失敗しました: {output_dir} - {e}")
            if progress_callback:
                # await を追加
                await progress_callback({"status": "error", "message": f"出力ディレクトリ作成失敗: {e}", "downloaded_bytes": 0, "total_bytes": 0})
            return False

    try:
        async with httpx.AsyncClient(timeout=None) as client: # タイムアウトを無効化 (大きなファイル用)
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                       'Referer': mp4_url} # Referer を追加 (必要になる場合がある)
            async with client.stream("GET", mp4_url, headers=headers, follow_redirects=True) as response:
                if response.status_code == 403:
                     logging.error(f"ダウンロードアクセス拒否 (403 Forbidden): {mp4_url} - Refererを確認してください。")
                     if progress_callback:
                          await progress_callback({"status": "error", "message": "アクセス拒否 (403)", "downloaded_bytes": 0, "total_bytes": 0})
                     return False
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                logging.info(f"ファイルサイズ: {total_size} bytes")

                if progress_callback:
                    await progress_callback({ # await を追加
                        "status": "downloading",
                        "downloaded_bytes": 0,
                        "total_bytes": total_size,
                        "percentage": 0.0,
                        "speed_bps": 0.0
                    })

                # 一時ファイルに書き込む (ダウンロード中断時のゴミを残さないため)
                temp_output_path = output_path + ".part"
                last_progress_update_time = start_time
                try:
                    with open(temp_output_path, 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                            if not chunk: # 空のチャンクが来たら終了？ (念のため)
                                break
                            f.write(chunk)
                            downloaded_size += len(chunk)

                            current_time = asyncio.get_event_loop().time()
                            # 進捗更新は一定間隔で行う (例: 0.5秒ごと)
                            if progress_callback and (current_time - last_progress_update_time > 0.5):
                                percentage = (downloaded_size / total_size * 100) if total_size > 0 else 0
                                elapsed_time = current_time - start_time
                                speed_bps = (downloaded_size / elapsed_time) * 8 if elapsed_time > 0 else 0 # bits per second

                                await progress_callback({ # await を追加
                                    "status": "downloading",
                                    "downloaded_bytes": downloaded_size,
                                    "total_bytes": total_size,
                                    "percentage": round(percentage, 2),
                                    "speed_bps": round(speed_bps, 2)
                                })
                                last_progress_update_time = current_time
                            # UI更新のための短い待機（任意）
                            # await asyncio.sleep(0.01)

                    # ダウンロード完了後、一時ファイルをリネーム
                    os.rename(temp_output_path, output_path)

                except Exception as write_err:
                     logging.error(f"ファイル書き込み/リネーム中にエラー: {write_err}", exc_info=True)
                     # 一時ファイルを削除
                     if os.path.exists(temp_output_path):
                          os.remove(temp_output_path)
                     if progress_callback:
                          await progress_callback({"status": "error", "message": f"ファイル書き込みエラー: {write_err}", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
                     return False


        if total_size > 0 and downloaded_size != total_size:
             logging.warning(f"ダウンロードサイズが一致しません: Expected={total_size}, Got={downloaded_size} for {output_path}")
             # 不完全なダウンロードとしてエラーにする
             if progress_callback:
                 await progress_callback({"status": "error", "message": "ダウンロードサイズ不一致", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
             # 不完全なファイルを削除
             if os.path.exists(output_path):
                  os.remove(output_path)
             return False

        logging.info(f"ダウンロード完了: {output_path} ({downloaded_size} bytes)")
        if progress_callback:
            await progress_callback({ # await を追加
                "status": "finished",
                "downloaded_bytes": downloaded_size,
                "total_bytes": total_size,
                "percentage": 100.0, # 完了時は100%
                "speed_bps": 0.0 # 完了時は0
            })
        return True # 成功時は True を返す

    except httpx.HTTPStatusError as e:
         logging.error(f"ダウンロード中にHTTPステータスエラーが発生しました: {mp4_url} - Status: {e.response.status_code}")
         if progress_callback:
             await progress_callback({"status": "error", "message": f"HTTPエラー: {e.response.status_code}", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
         return False
    except httpx.RequestError as e:
        logging.error(f"ダウンロード中にHTTPリクエストエラーが発生しました: {mp4_url} - {e}")
        if progress_callback:
            await progress_callback({"status": "error", "message": f"HTTPリクエストエラー: {e}", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
        return False
    except IOError as e:
         logging.error(f"ファイル操作エラーが発生しました: {output_path} - {e}")
         if progress_callback:
             await progress_callback({"status": "error", "message": f"ファイル操作エラー: {e}", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
         return False
    except Exception as e:
        logging.error(f"ダウンロード中に予期せぬエラーが発生しました: {mp4_url} - {e}", exc_info=True)
        if progress_callback:
            await progress_callback({"status": "error", "message": f"予期せぬエラー: {e}", "downloaded_bytes": downloaded_size, "total_bytes": total_size})
        return False


# --- 統合関数 ---
async def download_video_from_page(
    video_page_url: str,
    output_filename: str, # ファイル名のみを受け取る
    output_directory: str, # 出力ディレクトリを別途指定
    progress_callback: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None # コールバックを Coroutine に変更
) -> Optional[str]: # 成功時はダウンロードしたファイルのパス、失敗時は None を返すように変更
    """動画ページURLからMP4 URLを見つけてダウンロードし、成功したらファイルパスを返す"""

    # 1. MP4 URLを検索
    mp4_url = await find_mp4_url(video_page_url)
    if not mp4_url:
        logging.error(f"MP4 URLの取得に失敗しました: {video_page_url}")
        if progress_callback:
            await progress_callback({"status": "error", "message": "MP4 URL取得失敗"}) # await を追加
        return None # 失敗時は None を返す

    # 2. 出力パスを構築
    # ファイル名に使えない文字を置換
    safe_filename = "".join(c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in output_filename)
    # 拡張子がなければ .mp4 を付与
    if not safe_filename.lower().endswith('.mp4'):
        safe_filename += '.mp4'

    output_path = os.path.join(output_directory, safe_filename)

    # 3. 動画をダウンロード
    success = await download_video(mp4_url, output_path, progress_callback)

    if success:
         return output_path # 成功時はファイルパスを返す
    else:
         return None # 失敗時は None を返す


# --- テスト用 ---
async def test_progress_callback(progress_info: Dict[str, Any]):
    """テスト用の進捗コールバック関数"""
    status = progress_info.get("status")
    if status == "downloading":
        print(f"\rDownloading... {progress_info.get('percentage'):.2f}% "
              f"({progress_info.get('downloaded_bytes')}/{progress_info.get('total_bytes')}) "
              f"Speed: {progress_info.get('speed_bps', 0.0):.2f} bps", end="")
    elif status == "finished":
        print("\nDownload finished!")
    elif status == "error":
        print(f"\nDownload error: {progress_info.get('message')}")

async def main_test():
    # テスト用の動画ページURL (実際のURLに置き換える必要あり)
    test_video_page_url = "https://tktube.com/ja/videos/314819/fc2-ppv-4670832-4-27-21/" # ログにあったURL
    test_output_filename = "FC2-PPV-4670832 Test Video" # タイトルから生成される想定
    test_output_dir = "download_test" # テスト用出力ディレクトリ

    print(f"テストダウンロードを開始します: {test_video_page_url}")
    downloaded_path = await download_video_from_page(
        test_video_page_url,
        test_output_filename,
        test_output_dir,
        progress_callback=test_progress_callback
    )

    if downloaded_path:
        print(f"テストダウンロードが成功しました。ファイル: {downloaded_path}")
    else:
        print("テストダウンロードが失敗しました。")

if __name__ == '__main__':
    # web_app から実行されるので、ここでのロギング設定は不要になることが多い
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s [%(funcName)s] - %(message)s')
    asyncio.run(main_test())