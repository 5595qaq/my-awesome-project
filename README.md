# VLM+LLM Nursing Practical Exam Scoring System

這是一個基於 VLM (視覺語言模型) 與 LLM 架構的護理術科評分系統。系統包含 JavaScript 前端與 FastAPI (Python) 後端。影片先上傳到 Google Cloud Storage (GCS)，後端透過 Vertex AI 呼叫 Gemini 模型對 `gs://` 路徑的影片進行解析與術科自動評分。

> 目前僅供組內測試使用，前端是設計給組員測試 prompt/影片評分效果的工具，尚未考慮一般使用者的多人權限管理。

## 系統特色

- **事件驅動架構 (Event-Driven)**：採用高擴充性的 Worker 排程概念，完全解耦 API 請求與耗時推論任務。
- **即時進度監控**：前端透過 WebSocket 即時取得任務執行進度 (Uploading -> Processing -> Scoring)，並在頁面上呈現終端機風格的進度條與日誌。
- **資料庫狀態持久化**：所有的任務執行狀態與最終判定結果會被記錄至 PostgreSQL 資料庫中。
- **GCS 影片上傳與去重**：前端可直接選取本機影片檔案上傳到 GCS；若同檔名（轉檔後的 `*_1fps.mp4`）已存在於 bucket 中，會直接沿用既有的 `gs://` 路徑，不會重複轉檔、重複上傳。也可以直接貼上已存在的 `gs://` 路徑。
- **上傳前自動轉 1fps**：後端會先用 ffmpeg 把影片轉成 1fps（H.265）再上傳，統一 Vertex AI 讀到的影片格式，也大幅縮小檔案大小。
- **Vertex AI 認證**：後端統一使用 GCP service account 認證 Vertex AI／GCS，組員不需要各自準備或輸入 Gemini API Key。
- **彈性結果格式**：多個 Agent 產出的評分 JSON 欄位尚未統一，前端以通用卡片＋原始 JSON 檢視的方式呈現，方便邊測 prompt 邊看結果。
- **時間分段＋四 Agent 平行評分**：`Time_cuting.txt` 先對完整影片找出四個重疊時間區段，Agent_A ~ Agent_D 再同時分析各自區段；各 Agent 的 prompt 分別存放於 `backend/app/prompts/Agent_A.txt` ~ `Agent_D.txt`。
- **可靠工作派發**：PostgreSQL `NOTIFY` 負責即時喚醒 worker，advisory lock 防止多 worker 重複處理，週期 recovery 會重新派發遺漏通知或中斷的未完成任務。

## 系統運作流程與架構

系統捨棄了傳統的 API 直接阻塞或單機背景任務，改用基於 **PostgreSQL Pub/Sub** 的高階任務排程設計 (類似 Celery/RabbitMQ 的概念)，目前完整的執行流程為：

0. **[影片上傳]**：前端選取本機影片並上傳到 GCS（同檔名已存在則直接沿用），取得 `gs://` 路徑；也可以直接貼上既有的 `gs://` 路徑。
1. **[呼叫 API]**：前端帶著 `gs://` 路徑發起評分請求說：「我要上傳評分任務喔！」
2. **[API 回家]**：Backend 將任務與子邏輯寫入 PostgreSQL，標為 `pending` 之後立刻給前端回覆 HTTP 200，不直接親自處理耗時推論。
3. **[被動觸發]**：PostgreSQL 內建的 Trigger 發現資料表多了一筆 `pending` 紀錄，立刻大喊：「有新工作！」並向外發出 `NOTIFY` 廣播。
4. **[Worker 接手]**：後端 listener 聽到廣播後排入 job，取得 PostgreSQL advisory lock 的 worker 才會執行，避免多 worker 重複評分。
5. **[時間分段]**：`Time_cuting` 先讀取完整影片，產生 Agent_A ~ Agent_D 的重疊時間範圍。
6. **[平行評分]**：同時呼叫 Agent_A ~ Agent_D，每個 Agent 只會收到自己的原影片時間區段；單一後端程序最多同時發出四個 Vertex AI 請求。
7. **[過程回報]**：每個 Agent 完成時更新資料庫，再由 PostgreSQL 廣播給 WebSocket Manager 即時推送前端。

💡 **微服務化擴充潛力**：由於程式碼與架構被完全解開了，未來可以很輕鬆地將 `pg_listener` 與 `process_evaluation_job` 拆出去，獨立放到另外一台配備頂級 GPU 的機器上負責「專門跑運算」，達成完美的系統微服務化架構擴充！

### 核心模組架構

1. **Frontend**: 純 HTML, CSS, 與 vanilla JavaScript。透過 Fetch API 下達評估任務，並透過 WebSocket 監聽伺服器事件更新 DOM。
2. **Backend**: Python FastAPI，提供 REST API 創建任務，以及管理 WebSocket 節點。
3. **Database (Message Broker)**: PostgreSQL，除了使用 SQLAlchemy ORM 保存狀態外，更兼任 Pub/Sub 訊息佇列，掌控並觸發全域系統事件。
4. **VLM/LLM Engine**: Vertex AI 上的 Gemini 模型，讀取 GCS 影片提供視覺解析與最終護理步驟檢核表的邏輯統整。

## GCP / gcloud 首次設定（首次使用必看）

本專案使用 Vertex AI（不是個人 Gemini API Key）。`gcloud` 是用來設定 Google Cloud 的命令列工具，不需要像伺服器一樣持續「啟動」；首次完成下列設定後，平常只要啟動本專案即可。若組內已提供 GCP 專案、bucket 和可用憑證，可直接跳到「建立 `.env`」。

### 1. 安裝並初始化 gcloud CLI

先安裝 [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)，重新開啟終端機後確認指令可用：

```bash
gcloud --version
gcloud init
```

`gcloud init` 會引導登入並選擇預設專案；若瀏覽器沒有自動開啟，依終端機顯示的網址與驗證碼完成登入即可。日後若需要更換或重新登入 Google 帳號，再執行 `gcloud auth login`。

### 2. 選擇專案並啟用 API

請將下方的 `YOUR_PROJECT_ID` 換成實際的 GCP project ID（不是專案顯示名稱），且該專案必須已開通 Billing：

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com storage.googleapis.com
gcloud config get-value project
```

### 3. 建立 GCS bucket

Bucket 名稱在全球必須唯一；`YOUR_BUCKET_NAME` 請自行替換。Bucket 的區域不需要與下方的 `GCP_LOCATION=global` 相同：

```bash
gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=asia-east1 --uniform-bucket-level-access
```

若組內已有 bucket，略過此步並直接使用既有名稱。

### 4. 建立 service account 並授權

以下權限讓後端能呼叫 Vertex AI，並只對指定 bucket 讀寫影片：

```bash
gcloud iam service-accounts create vlm-evaluator --display-name="VLM Evaluator"
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member="serviceAccount:vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/aiplatform.user"
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME --member="serviceAccount:vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com" --role="roles/storage.objectAdmin"
```

`Storage Object Admin` 只允許管理 bucket 裡的影片物件，不包含修改 bucket 本身的設定。

### 5. 建立應用程式憑證

以下兩種方式擇一。建議優先使用「方式 A」的無私鑰認證；若組織政策禁止建立 service account 金鑰（錯誤訊息包含 `iam.disableServiceAccountKeyCreation`），也必須使用方式 A。

#### 方式 A：ADC + service account impersonation（推薦）

先查出目前登入帳號，將 `YOUR_GOOGLE_ACCOUNT` 替換成該 Email，再允許此使用者代用 service account：

```bash
gcloud auth list
gcloud iam service-accounts add-iam-policy-binding vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com --member="user:YOUR_GOOGLE_ACCOUNT" --role="roles/iam.serviceAccountTokenCreator" --condition=None
gcloud auth application-default login --impersonate-service-account="vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

最後一行會開啟瀏覽器，請使用同一個 Google 帳號完成授權。接著把產生的 ADC 檔複製到本專案的 `secrets/gcp-key.json`，讓 Docker Compose 可以掛載：

**Windows PowerShell：**

```powershell
New-Item -ItemType Directory -Force secrets
Copy-Item "$env:APPDATA\gcloud\application_default_credentials.json" ".\secrets\gcp-key.json"
```

**macOS / Linux：**

```bash
mkdir -p secrets
cp ~/.config/gcloud/application_default_credentials.json ./secrets/gcp-key.json
```

雖然此方式沒有 service account 私鑰，ADC 檔仍含有使用者授權資訊，必須視為敏感檔案保管。

#### 方式 B：service account JSON 金鑰

只有在組織允許建立金鑰時才使用此方式：

**Windows PowerShell：**

```powershell
New-Item -ItemType Directory -Force secrets
gcloud iam service-accounts keys create .\secrets\gcp-key.json --iam-account="vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

**macOS / Linux：**

```bash
mkdir -p secrets
gcloud iam service-accounts keys create ./secrets/gcp-key.json --iam-account="vlm-evaluator@YOUR_PROJECT_ID.iam.gserviceaccount.com"
```

> `secrets/` 已被 `.gitignore` 排除。無論使用 ADC 或 service account 金鑰，都請勿提交到 Git、貼到聊天室或公開分享；不再使用的 JSON 金鑰應至 IAM 撤銷。

### 6. 建立 `.env`

在專案根目錄建立 `.env`（同樣不會被 Git 追蹤）：

```env
GCP_PROJECT_ID=YOUR_PROJECT_ID
GCP_LOCATION=global
GCS_BUCKET_NAME=YOUR_BUCKET_NAME
GEMINI_MODEL_NAME=gemini-3.1-pro-preview
GCP_SA_KEY_PATH=./secrets/gcp-key.json
```

可用以下指令確認目前 gcloud 登入帳號、專案與 bucket：

```bash
gcloud auth list
gcloud config get-value project
gcloud storage ls gs://YOUR_BUCKET_NAME
```

## 如何啟動執行

### 方式一：使用 Docker 快速啟動（推薦 ✨）
為解決環境相依性與資料庫建構繁瑣的問題，本專案已支援 Docker 微服務容器化部署。
只需確保系統已安裝 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，並已完成上方「GCP 設定」：
1. 進入專案根目錄 (`my-awesome-project`) 開啟終端機。
2. 執行以下指令，一鍵自動建立 PostgreSQL 資料庫與 FastAPI 後端容器（Docker Compose 會自動讀取根目錄的 `.env`）：
   ```bash
   docker compose up -d --build
   ```
3. 查看後端啟動狀態與日誌：
   ```bash
   docker compose ps
   docker compose logs -f backend
   ```
4. 看到 Uvicorn 啟動完成後，開啟 `http://localhost:8000/docs`；能看到 FastAPI API 文件即表示後端已成功啟動。按 `Ctrl+C` 只會停止追蹤日誌，不會關閉容器。

停止服務：

```bash
docker compose down
```

若出現認證或 bucket 權限錯誤，先確認 `.env` 內的 project/bucket 是否正確，以及 `GCP_SA_KEY_PATH` 指向的 ADC 或金鑰 JSON 檔確實存在；修改 `.env` 後請重新執行 `docker compose up -d --build`。

### 方式二：手動本機環境設定
1. 確保已安裝 Python、PostgreSQL，以及 **ffmpeg**（需在 PATH 上可執行，影片上傳前會呼叫它轉成 1fps）。
2. 設定資料庫連線變數 (或直接使用預設 `postgresql://postgres:postgres@localhost:5432/vlm_eval`)。
3. 設定「GCP 設定」小節列出的環境變數，並將 `GOOGLE_APPLICATION_CREDENTIALS` 指向前面建立的 `secrets/gcp-key.json`（可以是 ADC 或 service account 金鑰）。注意：本機啟動時 Python 不會自動載入根目錄的 `.env`，必須先把變數載入目前的終端機工作階段。

   **Windows PowerShell：**
   ```powershell
   $env:GCP_PROJECT_ID="YOUR_PROJECT_ID"
   $env:GCP_LOCATION="global"
   $env:GCS_BUCKET_NAME="YOUR_BUCKET_NAME"
   $env:GEMINI_MODEL_NAME="gemini-3.1-pro-preview"
   $env:GOOGLE_APPLICATION_CREDENTIALS=(Resolve-Path ".\secrets\gcp-key.json").Path
   ```

   **macOS / Linux：**
   ```bash
   export GCP_PROJECT_ID="YOUR_PROJECT_ID"
   export GCP_LOCATION="global"
   export GCS_BUCKET_NAME="YOUR_BUCKET_NAME"
   export GEMINI_MODEL_NAME="gemini-3.1-pro-preview"
   export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/secrets/gcp-key.json"
   ```
4. 安裝相依套件：
   ```bash
   pip install -r backend/requirements.txt
   ```
5. 進入 `backend` 資料夾並啟動 Server：
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```
6. 開啟 `http://localhost:8000/docs` 確認後端成功啟動。

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
│   │   ├── prompts/
│   │   │   ├── Time_cuting.txt
│   │   │   ├── Agent_A.txt
│   │   │   ├── Agent_B.txt
│   │   │   ├── Agent_C.txt
│   │   │   └── Agent_D.txt
│   │   ├── schemas/
│   │   │   └── evaluation.py
│   │   ├── services/
│   │   │   ├── agents.py
│   │   │   ├── gcs_service.py
│   │   │   ├── gemini_service.py
│   │   │   └── video_service.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── main.py
│   │   └── ws_manager.py
└── README.md
```
