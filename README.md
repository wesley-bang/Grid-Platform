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
相同 `JWT_SECRET` 可在一小時內維持登入狀態。 

開啟 <http://127.0.0.1:8000/>，API 文件位於 <http://127.0.0.1:8000/docs>。

可用 `DATABASE_URL` 覆寫平台資料庫位置，以逗號分隔的 `CORS_ORIGINS` 設定允許來源。

## 上傳圖片處理

上傳視窗會顯示最終 32×32 預覽，並提供三種模式：

- 像素保真：嘗試還原被放大的像素網格，超過 32×32 時可拖曳裁切。
- 完整顯示：以 NEAREST 將完整內容等比例縮入 32×32。
- 平滑縮放：以預乘 Alpha 的高品質縮放處理一般插圖。

## 匯出遊戲端 assets.db

在「素材包」頁面點擊「匯出 .db」即可直接下載 Grid++ 引擎使用的 SQLite 檔。

匯出的檔案只包含 `sprites(id, name, tags, image_data)`，其中 `image_data` 是固定 4096 bytes 的 32×32 RGBA8888 原始資料。
