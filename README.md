# Grid++ 素材庫平台

供 Grid++ 遊戲素材上傳、搜尋、收藏、編組與匯出的 Web 平台。後端提供 REST API，並直接託管同一套原生 HTML/CSS/JavaScript 前端。

核心功能：

- 帳號註冊、登入、登出與個人資料管理
- 32×32 RGBA8888 素材上傳、預覽、搜尋與刪除
- 私人收藏資料夾
- 素材包編排與 Grid++ `assets.db` 匯出
- OpenAPI 文件與一致的 API 錯誤格式

## 技術組成

- Python 3.13
- FastAPI、Pydantic、Uvicorn
- SQLAlchemy、Alembic
- SQLite（預設開發資料庫）
- Pillow（圖片處理）
- pytest、HTTPX（測試）

## 專案結構

```text
app/
├── main.py              # FastAPI 應用程式與路由
├── models.py            # SQLAlchemy 資料模型
├── schemas.py           # API 回應模型
├── validation.py        # 請求驗證與正規化
├── image_processing.py  # 32×32 RGBA 圖片處理
├── security.py          # 密碼雜湊與 JWT
├── config.py            # 環境設定
├── database.py          # Engine、Session 與 FastAPI dependency
└── static/              # 內建前端
alembic/
├── env.py
└── versions/            # 資料庫遷移
docker/
├── entrypoint.sh        # 容器啟動：遷移後跑 uvicorn
└── nginx.conf           # 內層 nginx：靜態檔與 API 反代
tests/                   # API、資料庫與圖片處理測試
Dockerfile
docker-compose.yml
docker-compose.edge.yml  # 可選：讓前端 nginx 加入既有外部網路
```

## 本機開發

### 1. 建立環境

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
```

### 2. 設定環境變數

產生開發用 JWT secret：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

將結果填入 `.env` 的 `JWT_SECRET`。可用設定如下：

- `JWT_SECRET`：必填，至少 32 bytes；用於簽署一小時有效的 access token。
- `DATABASE_URL`：選填；預設為專案根目錄的 `grid_platform.db`。
- `CORS_ORIGINS`：選填；外部前端的允許來源，以逗號分隔，不接受 `*`。使用內建前端時不需設定。

行程環境變數的優先度高於 `.env`，部署環境應直接由平台注入設定。

### 3. 建立資料庫並啟動

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

- Web UI：<http://127.0.0.1:8000/>
- OpenAPI：<http://127.0.0.1:8000/docs>

## 開發指令

執行全部測試：

```bash
pytest
```

同步遠端變更後：

- `pyproject.toml` 有更新：執行 `python -m pip install -e ".[test]"`。
- `alembic/versions/` 有新 revision：執行 `alembic upgrade head`。

## API 與資料格式

需要登入的 API 使用 `Authorization: Bearer <token>`。Access token 有效期為一小時，登出後會立即撤銷。

素材在資料庫與 API 中皆使用固定 4096 bytes 的 32×32 RGBA8888 原始資料。`GET /sprites/{id}/image` 回傳 `application/octet-stream`，不是 PNG。

圖片上傳提供三種處理模式：

- `pixel`：偵測並保留像素網格，必要時裁切。
- `fit`：以 nearest-neighbor 將完整內容等比例縮入 32×32。
- `smooth`：以預乘 Alpha 的高品質取樣縮放一般插圖。

素材包由 `GET /packs/{id}/export` 匯出為 SQLite。檔案只包含 `sprites(id, name, tags, image_data)`，可直接供 Grid++ 引擎使用。

完整端點、請求欄位與回應格式以 `/docs` 產生的 OpenAPI 文件為準。

## 資料庫遷移

Schema 變更流程：

1. 修改 `app/models.py` 及相關應用程式碼。
2. 建立新 revision：`alembic revision -m "簡短說明"`；需要時加上 `--autogenerate`。
3. 人工檢查 upgrade 與 downgrade 內容。
4. 執行 `alembic upgrade head` 並補上相應測試。

遷移規範：

- 不修改已提交、可能已套用的 revision，也不更動既有 `revision` 或 `down_revision` ID。
- 每個獨立 schema 變更建立新的 revision。
- 不手動修改 `alembic_version`。
- 不以修改 `alembic.ini` 切換資料庫；使用 `DATABASE_URL`。

## Docker 部署

Compose 預設只走內部網路，不對宿主發 port。前端 nginx 提供 `app/static/`，其餘請求反代到 FastAPI。資料庫是 volume 裡的 SQLite，啟動時會跑 `alembic upgrade head`。

```bash
cp .env.example .env
# 填入 JWT_SECRET
docker compose up -d --build
docker compose down          # 不刪資料
docker compose down -v       # 連 volume 一起刪
```

未接外層 nginx 時，宿主打不到這個堆疊，這是預設行為。

### 接到伺服器既有的 nginx

讓前端 nginx 加入主機上已存在的 Docker network（外層 nginx 也必須在同一張網上）：

1. 在 `.env` 加上：

   ```bash
   COMPOSE_FILE=docker-compose.yml:docker-compose.edge.yml
   EDGE_NETWORK=nginx
   ```

   `EDGE_NETWORK` 改成實際的 network 名稱。

2. `docker compose up -d --build`

3. 外層 nginx 反代到這個堆疊，不要把主機專用 conf 放進本 repo：

   ```nginx
   proxy_pass http://grid-platform:80;
   ```

   並設 `client_max_body_size 6m`，轉發 `Host` 與 `X-Forwarded-For` / `X-Forwarded-Proto`。

別名固定為 `grid-platform`，與 compose 專案名無關。`docker compose down` 不會刪那張外部 network。
