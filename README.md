# tk-auto-dl

ダウンロード管理ツールの自動化プロジェクトです。このツールは、ダウンロードタスクを効率的に管理し、自動化します。

## 概要
tk-auto-dlは、ダウンロードタスクを管理するための自動化ツールです。以下の機能を提供します：
- ダウンロードタスクの自動化
- ダウンロード履歴の管理
- ダウンロードスケジュールの設定
- ダウンロード状況のモニタリング

## 構成
- `src/`: ソースコード
- `tests/`: テストコード
- `templates/`: テンプレートファイル
- `downloads/`: ダウンロードしたファイルの保存先
- `reference/`: 参考資料
- `plan.md`: プロジェクト計画
- `rules.md`: プロジェクトルール

## インストール
1. リポジトリをクローンします：
```bash
git clone https://github.com/yourusername/tk-auto-dl.git
```
2. プロジェクトディレクトリに移動します：
```bash
cd tk-auto-dl
```
3. バーチャル環境を作成します：
```bash
python -m venv venv
```
4. バーチャル環境をアクティブ化します：
```bash
source venv/bin/activate
```
5. リクエストされたパッケージをインストールします：
```bash
pip install -r requirements.txt
```

## 使用方法
1. ダウンロードタスクを定義します：
```python
# src/download_module.py
from .downloader import Downloader

def download_task(url, save_dir):
    downloader = Downloader()
    downloader.download(url, save_dir)
```
2. タスクを実行します：
```bash
python src/web_app.py
```

## テスト
テストは`pytest`を使用します：
```bash
pytest tests/
```

## ライセンス
MIT License

## 著作者
- [あなたの名前](https://github.com/yourusername)