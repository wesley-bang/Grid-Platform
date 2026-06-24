# Grid++ 素材庫平台

## 啟動

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
$env:JWT_SECRET = "請替換為至少 32 bytes 的安全隨機字串"
alembic upgrade head
uvicorn app.main:app --reload
```

開啟 <http://127.0.0.1:8000/>，API 文件位於 <http://127.0.0.1:8000/docs>。

可用 `DATABASE_URL` 覆寫平台資料庫位置，以逗號分隔的 `CORS_ORIGINS` 設定允許來源。

## 產生遊戲端 assets.db

```powershell
python create_assets.py export.json
python create_assets.py export.json custom-assets.db
```

省略輸出路徑時，會在輸入 JSON 同一目錄建立 `assets.db`。

