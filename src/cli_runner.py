#!/usr/bin/env python3
"""ヘッドレスでアプリを実行するCLIランナースクリプト"""

import asyncio
import logging
import os
from datetime import datetime
from src.web_app import get_download_queue_stats, get_upload_queue_stats, get_worker_stats
from src.web_app import main_background_loop

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

def generate_report_filename():
    """日付ベースのレポートファイル名を生成"""
    today = datetime.now().strftime("%Y%m%d")
    return f"{today}_report.txt"

async def run_and_generate_report():
    """バックグラウンドプロセスを実行し、レポートを生成"""
    start_time = datetime.now()
    logging.info(f"処理を開始します。開始時刻: {start_time}")
    
    try:
        await main_background_loop()
    except Exception as e:
        logging.error(f"エラーが発生しました: {e}", exc_info=True)
    finally:
        end_time = datetime.now()
        duration = end_time - start_time
        
        # ダウンロードキューの統計情報を取得
        download_stats = await get_download_queue_stats()
        
        # アップロードキューの統計情報を取得
        upload_stats = await get_upload_queue_stats()
        
        # ワーカーの状態を取得
        worker_stats = await get_worker_stats()
        
        # レポート生成
        report_content = f"""処理レポート
開始時刻: {start_time}
終了時刻: {end_time}
処理時間: {duration.total_seconds()}秒
処理状態: {"成功" if not isinstance(e, Exception) else "失敗"}

ダウンロードキュー統計情報:
  キューアイテム数: {download_stats["queue_count"]}
  アクティブワーカー: {download_stats["active_workers"]}
  総処理数: {download_stats["total_processed"]}
  総エラー数: {download_stats["total_errors"]}

アップロードキュー統計情報:
  キューアイテム数: {upload_stats["queue_count"]}
  アクティブワーカー: {upload_stats["active_workers"]}
  総処理数: {upload_stats["total_processed"]}
  総エラー数: {upload_stats["total_errors"]}

ワーカー状態:
  アクティブワーカー数: {worker_stats["active_workers"]}
  総ワーカー数: {worker_stats["total_workers"]}
"""
        
        # レポートファイルの保存
        report_filename = generate_report_filename()
        with open(report_filename, 'w') as f:
            f.write(report_content)
        
        logging.info(f"レポートを生成しました: {report_filename}")

if __name__ == "__main__":
    asyncio.run(run_and_generate_report())