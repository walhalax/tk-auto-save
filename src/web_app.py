import streamlit as st
from src.download_module import DownloadManager
from src.upload_module import Uploader
import os

def main():
    st.title("Auto Download & Upload App")

    # Temporary folder selection using OS file dialog
    if "temp_folder" not in st.session_state:
        with st.expander("一時フォルダの設定"):
            st.write("一時フォルダをOSのファイルブラウザから選択してください。")
            if st.button("フォルダを選択"):
                temp_folder = st.filebrowser.get_folder()
                if temp_folder:
                    st.session_state.temp_folder = temp_folder
                    st.success("一時フォルダが設定されました。")
                else:
                    st.error("フォルダが選択されませんでした。")

    if "temp_folder" in st.session_state:
        downloader = DownloadManager()
        downloader.set_temp_folder(st.session_state.temp_folder)
        uploader = Uploader()

        # UI components
        st.header("ダウンロードキュー")
        url = st.text_input("ダウンロードURL:", "")
        quality = st.select_slider("画質:", options=["highest", "lowest"])
        if st.button("追加"):
            downloader.add_to_queue(url, quality)
            st.success("キューに追加されました。")

        # Progress display
        if downloader.download_queue:
            st.header("ダウンロード進捗")
            progress = downloader.get_progress()
            st.progress(progress)
            st.write(f"ダウンロード进度: {progress}%")

        # Start/Stop controls
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Auto Start"):
                if "temp_folder" not in st.session_state:
                    st.error("一時フォルダが設定されていません。")
                else:
                    st.write("ダウンロードを開始します...")
                    # Start download process (to be implemented)
        with col2:
            if st.button("中断"):
                downloader.cancel_download()
                st.write("ダウンロードを中断します...")

if __name__ == "__main__":
    main()