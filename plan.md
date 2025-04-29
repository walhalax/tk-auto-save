# tk-auto-dl 開発計画案 (改訂版)

## 1. 目的

指定されたWebサイトから条件に合致する動画コンテンツを自動的にダウンロードし、指定されたファイルサーバーへアップロードするWebアプリケーションを開発する。

## 2. 主要機能

*   **自動巡回・検索:**
    *   指定カテゴリページ (`https://tktube.com/ja/categories/fc2/`) を巡回。
    *   未ダウンロードの動画コンテンツを自動検索。
    *   ページネーションに対応し、複数ページを巡回。
*   **条件フィルタリング:**
    *   公開日が3日以上経過している。
    *   コンテンツ評価（支持率）が70%以上。
    *   過去にアップロード成功していない。
*   **動画ダウンロード:**
    *   条件に合致した動画をキューに追加し、**最大2件** 同時ダウンロード。
    *   動画ページのHTMLを解析し、MP4ファイルのURLを抽出。
    *   ファイル形式はMP4。
    *   ファイル名は動画タイトルを使用。
    *   **ビットレート調整は行わず、サイトから取得可能な品質でダウンロードする。**
*   **ファイルアップロード:**
    *   ダウンロード完了後、指定ファイルサーバーへ自動アップロード（**最大2件** 同時）。
    *   サーバー: `filehub/UsbDisk1_Volume1/Adult/` (ユーザー名: admin, パスワード: admin)
    *   動画タイトルのプレフィックス (`FC2-PPV-***`) に基づきフォルダを作成/選択。
    *   アップロード先フォルダ内のファイル名 (`FC2-PPV-*******`) と比較し、重複をチェック。重複する場合はダウンロードしない。
*   **Web UI:**
    *   "Auto Start" ボタンによる処理開始。
    *   ダウンロード/アップロードキューの表示。
    *   各タスクの進捗状況（%表示）。
    *   中断/レジューム機能。

## 3. 技術スタック（提案）

*   **バックエンド:** Python
    *   Webフレームワーク: **FastAPI** (非同期処理に適しているため選択)
    *   HTTPリクエスト: `httpx` (非同期対応)
    *   HTML解析: `Beautiful Soup 4`
    *   ファイルサーバー接続: **`pysmbclient` (SMB/CIFS接続用と仮定。プロトコル確定後に変更の可能性あり)**
    *   並行処理: `asyncio`, `concurrent.futures` (最大ワーカー数: 2)
*   **フロントエンド:** HTML, CSS, JavaScript (Fetch APIによる非同期更新)
*   **データベース（状態管理用）:** SQLite または JSONファイル (処理済み動画リスト、キューの状態管理)
*   **バージョン管理:** Git

## 4. 開発ステップ

1.  **環境構築:**
    *   Python仮想環境 (`venv`) を作成。(ルール37)
    *   必要なライブラリ (`FastAPI`, `uvicorn`, `httpx`, `BeautifulSoup4`, `pysmbclient` 等) を `requirements.txt` に記述し、インストール。
2.  **コアモジュール開発:**
    *   **`content_scraper.py`:** (変更なし)
    *   **`download_module.py`:**
        *   動画ページHTMLからMP4 URLを抽出。
        *   **ビットレート調整ロジックは削除。** ストリーミングダウンロード、進捗計算。
        *   ファイル名生成。
        *   中断・再開ロジック。
    *   **`upload_module.py`:**
        *   ファイルサーバーへの接続（認証情報利用、**プロトコルは実装時に確定**）。
        *   フォルダ存在確認・作成。
        *   重複ファイルチェック。
        *   ファイルアップロード処理（進捗計算）。
        *   中断・再開ロジック。
    *   **`status_manager.py`:** (新規)
        *   ダウンロード/アップロードキューの管理。
        *   処理済み動画リストの管理（SQLite or JSON）。
        *   タスク状態（待機中、処理中、完了、エラー、中断）の管理。
3.  **Webアプリケーション開発:**
    *   **`web_app.py`:** (FastAPI)
        *   基本的なルーティング設定 (`/`, `/status`, `/start`, `/stop`, `/resume`)。
        *   バックエンド処理のトリガー。
        *   ステータス情報をJSONでフロントエンドに提供するAPIエンドポイント (WebSocket利用も検討可)。
    *   **`templates/index.html`:** (変更なし)
4.  **統合とテスト:** (変更なし)
5.  **ドキュメント作成:** (変更なし)
6.  **バージョン管理:** (変更なし)

## 5. Mermaid ダイアグラム

### 全体フロー

```mermaid
graph TD
    A[UI: Auto Start Clicked] --> B[Controller: Start Process];
    B --> C[QueueManager: Add Scrape Task];
    C --> D{Scraper: Scrape Target Page};
    D -- Videos Found --> E{Scraper: Filter Videos};
    E -- Eligible Videos --> F[QueueManager: Add Download Tasks (Max 2)];
    E -- No Eligible Videos / End of Pages --> G[Controller: Process Finished];
    D -- No Videos / Error --> G;
    E -- Need Next Page --> H{Scraper: Go to Next Page};
    H --> D;
    F --> I{QueueManager: Start Download Worker (Max 2)};
    I -- Download Task --> J{Downloader: Download MP4};
    J -- Download Complete --> K[QueueManager: Add Upload Task (Max 2)];
    J -- Download Error/Interrupted --> L[QueueManager: Mark Task Error/Paused];
    K --> M{QueueManager: Start Upload Worker (Max 2)};
    M -- Upload Task --> N{Uploader: Check Destination & Duplicates};
    N -- OK to Upload --> O{Uploader: Upload MP4};
    N -- Duplicate Found / Error --> P[QueueManager: Mark Task Error/Skipped];
    O -- Upload Complete --> Q[QueueManager: Mark Task Completed];
    O -- Upload Error/Interrupted --> P;
    subgraph UI Interaction
        R[UI: Display Status from QueueManager]
        S[UI: Stop/Resume Buttons] --> T[Controller: Control QueueManager]
    end
```

### コンポーネント構成

```mermaid
graph TD
    subgraph WebApp [Web Application]
        UI[Web UI (HTML/CSS/JS)]
        Controller[web_app.py (FastAPI)]
    end
    subgraph CoreLogic [Core Logic Modules]
        Scraper[content_scraper.py]
        Downloader[download_module.py]
        Uploader[upload_module.py]
        QueueManager[status_manager.py]
        DB[(Status DB: SQLite/JSON)]
    end
    subgraph External [External Services]
        TargetSite[tktube.com]
        FileServer[File Server (filehub)]
    end

    UI -- HTTP Request --> Controller;
    Controller -- Calls --> QueueManager;
    Controller -- Calls --> Scraper;
    Controller -- Calls --> Downloader;
    Controller -- Calls --> Uploader;
    QueueManager -- Manages --> DB;
    Scraper -- HTTP Request --> TargetSite;
    Downloader -- HTTP Request --> TargetSite;
    Downloader -- Writes --> LocalStorage[Local Temp Storage];
    Uploader -- Reads --> LocalStorage;
    Uploader -- SMB/FTP/SFTP? --> FileServer;
```

## 6. **重要:** 事前確認事項

*   **ファイルサーバー接続プロトコル:** `filehub` への接続プロトコル (SMB/CIFS, FTP, SFTP等) を**実装開始前に特定してください。** これにより、`upload_module.py` で使用するライブラリが決まります。
*   **利用規約の確認:** `tktube.com` の**利用規約を必ず確認し、自動的なコンテンツのダウンロードおよび再配布（ファイルサーバーへのアップロードを含む）が許可されているかを確認してください。** 規約に違反する場合、このプロジェクトは倫理的・法的な問題を引き起こす可能性があり、開発を進めるべきではありません。**この確認はユーザー様の責任において実施をお願いいたします。**