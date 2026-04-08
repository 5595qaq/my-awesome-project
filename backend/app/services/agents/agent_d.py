import asyncio
from app.ws_manager import manager

# --- 預留 Prompt 區塊 (待錄製影片後啟用) ---
# AGENT_D_SYSTEM_PROMPT = """
# Role: 護理技術評分專家 (Agent D)
# 任務：針對「無菌技術抽藥」步驟 21-30 進行細節判定。
# 視覺錨點：Vial 藥瓶、針筒推桿、手部回套動作。
# 語言規則：內部推理使用 English CoT，最終輸出中文。
# """

async def evaluate(video_paths: list, api_key: str, job_id: str):
    """
    Agent D 負責抽藥核心步驟與收尾判定。
    """
    # 透過 WebSocket 向前端推播目前進度
    await manager.broadcast_to_job("PROGRESS_UPDATE", {
        "stage": "LLM_SCORING", 
        "message": "Agent D (精確抽藥) 正在啟動視覺推理分析..."
    }, job_id)

    # 模擬 VLM 運算耗時（目前為 Mock 階段）
    await asyncio.sleep(4) 

    # 回傳結構：這部分的 item 內容會直接顯示在 index.html 的表格中
    return {
        "agent": "Agent_D",
        "score": 95,
        "checklist": [
            {
                "item": "步驟 23-24：倒舉 Vial 瓶且針尖維持在液面下", 
                "passed": True
            },
            {
                "item": "步驟 25：抽藥後確實平視刻度核對劑量", 
                "passed": True
            },
            {
                "item": "步驟 28：落實安全規範，使用「單手回套」針頭技術", 
                "passed": True
            },
            {
                "item": "步驟 29：於丟棄空瓶前再次進行藥品三讀", 
                "passed": True
            }
        ],
        "details": "Agent D 判定報告：學生在抽藥過程中的無菌意識良好，單手回套動作標準，有效預防針扎風險。"
    }
