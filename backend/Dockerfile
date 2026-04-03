# 使用輕量級的 Python 作為基底映像檔
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 避免 Python 產生 .pyc 檔案並讓輸出直接顯示於終端機（有助於查看 log）
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 複製依賴套件清單並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 將專案內所有的程式碼複製到容器內
COPY . .

# 暴露 FastAPI 預設的 Port 8000
EXPOSE 8000

# 啟動命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]