from app.services.agents import agent_d

class Orchestrator:
    async def run_evaluation(self, exam_type: str, video_paths: list, api_key: str, job_id: str):
        """
        中控調度器：目前設定為不論前端選什麼，都統一交給 Agent D 測試。
        """
        print(f"Orchestrator: 收到 '{exam_type}' 請求，指派 Agent D 執行...")
        
        # 執行 Agent D
        result = await agent_d.evaluate(video_paths, api_key, job_id)
        
        # 整理成符合前端顯示需求的 JSON 格式
        return {
            "passed": result["score"] >= 60,
            "score": result["score"],
            "checklist": result["checklist"],
            "details": result["details"]
        }

# 建立單例物件
orchestrator = Orchestrator()
