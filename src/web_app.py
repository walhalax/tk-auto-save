import streamlit as st
from src.download_module import DownloadManager # Uploaderは削除
import os
import time
import logging # ロギングを追加

# ロギング設定 (download_moduleと合わせるか、アプリ固有の設定を行う)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# DownloadManagerのインスタンスをセッション状態で管理
if "download_manager" not in st.session_state:
    st.session_state.download_manager = DownloadManager()

manager: DownloadManager = st.session_state.download_manager

def main():
    st.title("YouTube Auto Downloader") # タイトル変更

    # --- 設定セクション ---
    with st.expander("設定", expanded=True): # 最初から開いておく
        # 一時フォルダ設定 (テキスト入力に変更)
        current_temp_folder = manager._temp_folder # 現在の設定値を取得
        temp_folder_input = st.text_input("一時フォルダ (絶対パス推奨):", value=current_temp_folder)
        if st.button("一時フォルダを設定"):
            try:
                manager.set_temp_folder(temp_folder_input)
                st.success(f"一時フォルダが '{temp_folder_input}' に設定されました。")
                # 画面を再描画して入力フィールドの値を更新
                st.rerun()
            except ValueError as e:
                st.error(f"フォルダ設定エラー: {e}")
            except Exception as e:
                st.error(f"予期せぬエラーが発生しました: {e}")
                logging.error(f"一時フォルダ設定中のエラー: {e}", exc_info=True)

    # --- ダウンロード追加セクション ---
    st.header("ダウンロード追加")
    url = st.text_input("YouTube URL:", key="url_input") # keyを設定して入力保持
    # qualityの選択肢をyt-dlpに合わせて変更
    quality_options = {"最高画質": "highest", "最低画質": "lowest"}
    selected_quality_label = st.selectbox("画質:", options=list(quality_options.keys()))
    selected_quality_value = quality_options[selected_quality_label]

    if st.button("キューに追加"):
        if url:
            manager.add_to_queue(url, selected_quality_value)
            st.success(f"キューに追加されました: {url}")
            # 入力フィールドをクリアするためにキーを使って値をリセット (st.rerunでも可)
            st.session_state.url_input = ""
            st.rerun() # キュー表示を更新
        else:
            st.warning("URLを入力してください。")

    # --- 実行制御セクション ---
    st.header("実行制御")
    col1, col2 = st.columns(2)
    with col1:
        # 実行中でなければ開始ボタンを表示
        if not manager.is_running():
            if st.button("ダウンロード開始", key="start_button"):
                if not manager.download_queue.empty():
                    try:
                        # 一時フォルダが実際に存在するか確認
                        if not os.path.isdir(manager._temp_folder):
                             st.error(f"一時フォルダが見つかりません: {manager._temp_folder}。設定を確認してください。")
                        else:
                            manager.start_download()
                            st.info("ダウンロード処理を開始しました。")
                            st.rerun() # ボタンの状態を更新
                    except Exception as e:
                        st.error(f"ダウンロード開始エラー: {e}")
                        logging.error(f"ダウンロード開始中のエラー: {e}", exc_info=True)

                else:
                    st.warning("ダウンロードキューが空です。")
        else:
            st.button("ダウンロード開始", key="start_button_disabled", disabled=True) # 実行中は無効化

    with col2:
         # 実行中であればキャンセルボタンを表示
        if manager.is_running():
            if st.button("ダウンロード中断", key="cancel_button"):
                manager.cancel_download()
                st.warning("ダウンロードの中断を要求しました。")
                st.rerun() # ボタンの状態を更新
        else:
             st.button("ダウンロード中断", key="cancel_button_disabled", disabled=True) # 停止中は無効化


    # --- 進捗表示セクション ---
    st.header("現在のダウンロード進捗")
    progress_data = manager.get_progress()
    status = progress_data.get("status", "idle")
    percentage = progress_data.get("percentage", 0)
    filename = progress_data.get("filename", "")
    error_msg = progress_data.get("error")
    current_url = progress_data.get("url", "")

    if status == "downloading":
        st.info(f"ダウンロード中: {filename} ({current_url})")
        st.progress(int(percentage))
        st.write(f"{percentage:.2f}%")
    elif status == "starting":
        st.info(f"開始中: {current_url}")
        st.progress(0)
    elif status == "finished":
        st.success(f"完了: {filename}")
        st.progress(100)
    elif status == "cancelling":
        st.warning(f"キャンセル中: {filename} ({current_url})")
        st.progress(int(percentage)) # キャンセル時点の進捗を表示
    elif status == "cancelled":
        st.warning(f"キャンセル完了: {filename} ({current_url})")
    elif status == "error":
        st.error(f"エラー: {filename} ({current_url}) - {error_msg}")
    elif status == "idle":
        st.write("待機中")
    else:
         st.write(f"不明なステータス: {status}")


    # --- キュー表示セクション ---
    st.header("ダウンロードキュー")
    queue_items = manager.get_queue_status()
    if queue_items:
        # DataFrameで見やすく表示
        import pandas as pd
        df_queue = pd.DataFrame(queue_items)
        st.dataframe(df_queue[['url', 'quality', 'status']], use_container_width=True)
    else:
        st.write("キューは空です。")

    # --- 履歴表示セクション ---
    st.header("ダウンロード履歴")
    history_items = manager.get_history()
    if history_items:
        # DataFrameで見やすく表示
        import pandas as pd
        df_history = pd.DataFrame(history_items)
        # UNIXタイムスタンプを日時に変換
        df_history['timestamp'] = pd.to_datetime(df_history['timestamp'], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Tokyo')
        st.dataframe(df_history[['timestamp', 'filename', 'status', 'quality', 'url', 'error']], use_container_width=True)
    else:
        st.write("履歴はありません。")

    # 定期的に画面を更新して進捗を表示 (ダウンロード実行中のみ)
    if manager.is_running():
        time.sleep(1) # ポーリング間隔
        st.rerun()


if __name__ == "__main__":
    main()