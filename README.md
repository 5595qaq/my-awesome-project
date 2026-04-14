# VLM+LLM Nursing Practical Exam Scoring System

這是一個基於 VLM (視覺語言模型) 與 LLM 架構的護理術科評分系統。系統包含 JavaScript 前端與 FastAPI (Python) 後端。使用者可以輸入自備的 Gemini API Key，透過提供本機影片的絕對路徑，以減少檔案傳輸時間，直接對影片進行解析與術科自動評分。

## 系統特色

- **事件驅動架構 (Event-Driven)**：採用高擴充性的 Worker 排程概念，完全解耦 API 請求與耗時推論任務。
- **即時進度監控**：前端透過 WebSocket 即時取得任務執行進度 (Uploading -> Processing -> Scoring)，並在頁面上呈現終端機風格的進度條與日誌。
- **資料庫狀態持久化**：所有的任務執行狀態與最終判定結果 (Pass/Fail, 分數以及 Checklist) 會被記錄至 PostgreSQL 資料庫中。
- **安全性考量**：API Key 僅於單次執行期間記憶體內傳遞，不會將使用者的 Gemini API Token 寫入資料庫持久化。

## 系統運作流程與架構

系統捨棄了傳統的 API 直接阻塞或單機背景任務，改用基於 **PostgreSQL Pub/Sub** 的高階任務排程設計 (類似 Celery/RabbitMQ 的概念)，目前完整的執行流程為：

1. **[呼叫 API]**：前端發起評分請求說：「我要上傳評分任務喔！」
2. **[API 回家]**：Backend 將任務與子邏輯寫入 PostgreSQL，標為 `pending` 之後立刻給前端回覆 HTTP 200，不直接親自處理耗時推論。
3. **[被動觸發]**：PostgreSQL 內建的 Trigger 發現資料表多了一筆 `pending` 紀錄，立刻大喊：「有新工作！」並向外發出 `NOTIFY` 廣播。
4. **[Worker 接手]**：後端 `main.py` 的獨立 listener 聽到廣播，發現是一個新的 `pending` 任務，便馬上指派資源在背景啟動 `process_evaluation_job` 函式獨立運算。
5. **[過程回報]**：背景 AI 每執行一步，就更新一遍資料庫；狀態更改後，資料庫又會觸發新的廣播給 WebSocket Manager，並即時發散推送給前端。

💡 **微服務化擴充潛力**：由於程式碼與架構被完全解開了，未來可以很輕鬆地將 `pg_listener` 與 `process_evaluation_job` 拆出去，獨立放到另外一台配備頂級 GPU 的機器上負責「專門跑運算」，達成完美的系統微服務化架構擴充！

### 核心模組架構

1. **Frontend**: 純 HTML, CSS, 與 vanilla JavaScript。透過 Fetch API 下達評估任務，並透過 WebSocket 監聽伺服器事件更新 DOM。
2. **Backend**: Python FastAPI，提供 REST API 創建任務，以及管理 WebSocket 節點。
3. **Database (Message Broker)**: PostgreSQL，除了使用 SQLAlchemy ORM 保存狀態外，更兼任 Pub/Sub 訊息佇列，掌控並觸發全域系統事件。
4. **VLM/LLM Engine**: Google Gemini API 提供影片的視覺解析與最終護理步驟檢核表的邏輯統整。

## 如何啟動執行

### 方式一：使用 Docker 快速啟動（推薦 ✨）
為解決環境相依性與資料庫建構繁瑣的問題，本專案已支援 Docker 微服務容器化部署。
只需確保系統已安裝 [Docker Desktop](https://www.docker.com/products/docker-desktop/)：
1. 進入專案根目錄 (`my-awesome-project`) 開啟終端機。
2. 執行以下指令，一鍵自動建立 PostgreSQL 資料庫與 FastAPI 後端容器：
   ```bash
   docker-compose up -d --build
   ```
3. 容器啟動後，API 伺服器將運行於 `http://localhost:8000`。

### 方式二：手動本機環境設定
1. 確保已安裝 Python 以及 PostgreSQL。
2. 設定資料庫連線變數 (或直接使用預設 `postgresql://postgres:postgres@localhost:5432/vlm_eval`)。
3. 安裝相依套件：
   ```bash
   pip install fastapi uvicorn sqlalchemy psycopg2-binary
   ```
4. 進入 `backend` 資料夾並啟動 Server：
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

### 前端執行方式
1. 無需特別的伺服器。請使用檔案總管進入 `frontend` 資料夾，直接**對著 `index.html` 點擊兩下**開啟，或是將 `index.html` 檔案**直接拖曳到您的瀏覽器視窗**中。
   *(注意：請不要直接在網址列手動輸入 `frontend/index.html`，否則瀏覽器會當成網址搜尋而報錯)*
2. 填入您的 Gemini API Key、學生學號、評估項目，以及欲解析的**本機完整絕對路徑影片**（例如：`D:/Data/Videos/cam1.mp4`）。
3. 點擊「Start Evaluation」進行即時評分！

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
│   │   │       └── evaluations.py
│   │   ├── models/
│   │   │   └── evaluation.py
│   │   ├── schemas/
│   │   │   └── evaluation.py
│   │   ├── services/
│   │   │   └── gemini_service.py
│   │   ├── db.py
│   │   ├── main.py
│   │   └── ws_manager.py
└── README.md
```
