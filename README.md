# VLM+LLM Nursing Practical Exam Scoring System

這是一個基於 VLM (視覺語言模型) 與 LLM 架構的護理術科評分系統。系統包含 JavaScript 前端與 FastAPI (Python) 後端。使用者可以輸入自備的 Gemini API Key，透過提供本機影片的絕對路徑，以減少檔案傳輸時間，直接對影片進行解析與術科自動評分。

## 系統特色

- **純本地前端與背景處理**：採用 FastAPI 背景任務處理長時間的影片上傳與模型推論。
- **支援多種處理模式**：
  - **Standard 模式**：即時分析影片，速度較快，適用於快速評分。
  - **Batch 模式**：批次處理影片，適用於大量影片與節省 API 成本（採定時輪詢機制定期確認狀態）。
- **即時進度監控**：前端透過 WebSocket 即時取得任務執行進度 (Uploading -> Processing -> Scoring)，並在頁面上呈現終端機風格的進度條與日誌。
- **資料庫狀態持久化**：所有的任務執行狀態與最終判定結果 (Pass/Fail, 分數以及 Checklist) 會被記錄至 PostgreSQL 資料庫中。
- **安全性考量**：API Key 僅於單次執行期間記憶體內傳遞，不會將使用者的 Gemini API Token 寫入資料庫持久化。

## 系統架構

1. **Frontend**: 純 HTML, CSS, 與 vanilla JavaScript。透過 Fetch API 下達評估任務，並透過 WebSocket 監聽伺服器事件更新 DOM。
2. **Backend**: Python FastAPI，提供 REST API 創建任務，以及 WebSocket 節點作即時進度推播。
3. **Database**: PostgreSQL，使用 SQLAlchemy ORM 存取 `EvaluationJob`，以保存任務狀態與結果。
4. **VLM/LLM Engine**: Google Gemini API 提供影片的視覺解析與最終護理步驟檢核表的邏輯統整。

## 如何啟動執行

### 後端環境設定
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
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── backend/
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
