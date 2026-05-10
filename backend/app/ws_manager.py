from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    def __init__(self):
        # 負責記憶哪個 job_id 對應哪些 WebSocket 連線
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, job_id: str):
        # 🚨 最重要的一行：接起前端的連線請求
        await websocket.accept()
        
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)

    def disconnect(self, websocket: WebSocket, job_id: str):
        if job_id in self.active_connections:
            if websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

    async def broadcast_to_job(self, event: str, payload: dict, job_id: str):
        if job_id in self.active_connections:
            message = {"event": event, "payload": payload}
            # 使用 [:] 複製一份清單，避免在發送時迴圈出錯
            for connection in self.active_connections[job_id][:]:
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection, job_id)

manager = ConnectionManager()