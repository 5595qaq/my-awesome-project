# VLM+LLM Nursing Practical Exam Scoring System

這是一個基於 VLM (視覺語言模型) 與 LLM 架構的護理術科評分系統。系統包含 JavaScript 前端與 FastAPI (Python) 後端。影片先上傳到 Google Cloud Storage (GCS)，後端透過 Vertex AI 呼叫 Gemini 模型對 `gs://` 路徑的影片進行解析與術科自動評分。

> 目前僅供組內測試使用，前端是設計給組員測試 prompt/影片評分效果的工具，尚未考慮一般使用者的多人權限管理。

## 系統特色

- **事件驅動架構 (Event-Driven)**：採用高擴充性的 Worker 排程概念，完全解耦 API 請求與耗時推論任務。
- **即時進度監控**：前端透過 WebSocket 即時取得任務執行進度 (Uploading -> Processing -> Scoring)，並在頁面上呈現終端機風格的進度條與日誌。
- **資料庫狀態持久化**：所有的任務執行狀態與最終判定結果會被記錄至 PostgreSQL 資料庫中。
- **GCS 影片上傳與去重**：前端可直接選取本機影片檔案上傳到 GCS；若同檔名的影片已存在於 bucket 中，會直接沿用既有的 `gs://` 路徑，不會重複上傳。也可以直接貼上已存在的 `gs://` 路徑。
- **Vertex AI 認證**：後端統一使用 GCP service account 認證 Vertex AI／GCS，組員不需要各自準備或輸入 Gemini API Key。
- **彈性結果格式**：多個 Agent 產出的評分 JSON 欄位尚未統一，前端以通用卡片＋原始 JSON 檢視的方式呈現，方便邊測 prompt 邊看結果。

## 系統運作流程與架構

系統捨棄了傳統的 API 直接阻塞或單機背景任務，改用基於 **PostgreSQL Pub/Sub** 的高階任務排程設計 (類似 Celery/RabbitMQ 的概念)，目前完整的執行流程為：

0. **[影片上傳]**：前端選取本機影片並上傳到 GCS（同檔名已存在則直接沿用），取得 `gs://` 路徑；也可以直接貼上既有的 `gs://` 路徑。
1. **[呼叫 API]**：前端帶著 `gs://` 路徑發起評分請求說：「我要上傳評分任務喔！」
2. **[API 回家]**：Backend 將任務與子邏輯寫入 PostgreSQL，標為 `pending` 之後立刻給前端回覆 HTTP 200，不直接親自處理耗時推論。
3. **[被動觸發]**：PostgreSQL 內建的 Trigger 發現資料表多了一筆 `pending` 紀錄，立刻大喊：「有新工作！」並向外發出 `NOTIFY` 廣播。
4. **[Worker 接手]**：後端 `main.py` 的獨立 listener 聽到廣播，發現是一個新的 `pending` 任務，便馬上指派資源在背景啟動 `process_evaluation_job` 函式獨立運算。
5. **[過程回報]**：背景 AI 每執行一步，就更新一遍資料庫；狀態更改後，資料庫又會觸發新的廣播給 WebSocket Manager，並即時發散推送給前端。

💡 **微服務化擴充潛力**：由於程式碼與架構被完全解開了，未來可以很輕鬆地將 `pg_listener` 與 `process_evaluation_job` 拆出去，獨立放到另外一台配備頂級 GPU 的機器上負責「專門跑運算」，達成完美的系統微服務化架構擴充！

### 核心模組架構

1. **Frontend**: 純 HTML, CSS, 與 vanilla JavaScript。透過 Fetch API 下達評估任務，並透過 WebSocket 監聽伺服器事件更新 DOM。
2. **Backend**: Python FastAPI，提供 REST API 創建任務，以及管理 WebSocket 節點。
3. **Database (Message Broker)**: PostgreSQL，除了使用 SQLAlchemy ORM 保存狀態外，更兼任 Pub/Sub 訊息佇列，掌控並觸發全域系統事件。
4. **VLM/LLM Engine**: Vertex AI 上的 Gemini 模型，讀取 GCS 影片提供視覺解析與最終護理步驟檢核表的邏輯統整。

## GCP 設定（首次使用必看）

本專案改用 Vertex AI（而非個人 Gemini API Key），請先在 GCP 專案內完成以下設定：

1. 建立或選定一個 GCP 專案，並開通 Billing（可使用 $300 免費試用額度）。
2. 啟用 **Vertex AI API** 與 **Cloud Storage API**。
3. 建立一個 GCS bucket 存放影片（例如 `vlm_on99`）。
4. 建立一個 service account，賦予 `Vertex AI User` 與 `Storage Object Admin`（或至少對該 bucket 的讀寫）權限，並下載其 JSON 金鑰。
5. 在專案根目錄建立 `.env` 檔（此檔案已被 `.gitignore` 排除，不會進版本庫）：
   ```env
   GCP_PROJECT_ID=your-gcp-project-id
   GCP_LOCATION=us-central1
   GCS_BUCKET_NAME=your-bucket-name
   GEMINI_MODEL_NAME=gemini-2.5-flash
   GCP_SA_KEY_PATH=./secrets/gcp-key.json
   ```
6. 把下載的 service account 金鑰放到 `GCP_SA_KEY_PATH` 指定的路徑（預設 `secrets/gcp-key.json`，同樣已被 `.gitignore` 排除）。

## 如何啟動執行

### 方式一：使用 Docker 快速啟動（推薦 ✨）
為解決環境相依性與資料庫建構繁瑣的問題，本專案已支援 Docker 微服務容器化部署。
只需確保系統已安裝 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，並已完成上方「GCP 設定」：
1. 進入專案根目錄 (`my-awesome-project`) 開啟終端機。
2. 執行以下指令，一鍵自動建立 PostgreSQL 資料庫與 FastAPI 後端容器（`docker-compose` 會自動讀取根目錄的 `.env`）：
   ```bash
   docker-compose up -d --build
   ```
3. 容器啟動後，API 伺服器將運行於 `http://localhost:8000`。

### 方式二：手動本機環境設定
1. 確保已安裝 Python 以及 PostgreSQL。
2. 設定資料庫連線變數 (或直接使用預設 `postgresql://postgres:postgres@localhost:5432/vlm_eval`)。
3. 設定「GCP 設定」小節列出的環境變數，並將 `GOOGLE_APPLICATION_CREDENTIALS` 指向你下載的 service account 金鑰路徑。
4. 安裝相依套件：
   ```bash
   pip install -r backend/requirements.txt
   ```
5. 進入 `backend` 資料夾並啟動 Server：
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

### 前端執行方式
1. 無需特別的伺服器。請使用檔案總管進入 `frontend` 資料夾，直接**對著 `index.html` 點擊兩下**開啟，或是將 `index.html` 檔案**直接拖曳到您的瀏覽器視窗**中。
   *(注意：請不要直接在網址列手動輸入 `frontend/index.html`，否則瀏覽器會當成網址搜尋而報錯)*
2. 選擇評估項目後，在「Upload Videos to GCS」選取本機影片檔案並按下「Upload to GCS」——同檔名的影片若已存在於 bucket 中會直接沿用，不會重複上傳。也可以在下方文字框直接貼上已存在的 `gs://` 路徑。
3. 點擊「Start Evaluation」進行即時評分！結果會依 Agent 分組顯示，並提供「View Raw JSON Response」查看模型原始輸出，方便測試/調整 prompt。

## 目錄結構
```text
my-awesome-project/
├── docker-compose.yml
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── backend/
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   ├── app/
│   │   ├── api/
│   │   │   └── endpoints/
│   │   │       ├── evaluations.py
│   │   │       └── uploads.py
│   │   ├── models/
│   │   │   └── evaluation.py
│   │   ├── schemas/
│   │   │   └── evaluation.py
│   │   ├── services/
│   │   │   ├── agents.py
│   │   │   ├── gcs_service.py
│   │   │   └── gemini_service.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── main.py
│   │   └── ws_manager.py
└── README.md
```
