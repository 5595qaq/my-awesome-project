import asyncio
from app.services.agents import agent_a, agent_d

class Orchestrator:
    # 定義每個考試要用到的 Agent 組合
    EXAM_CONFIG = {
        "vial_powder_extraction": [agent_a, agent_d],
        "suction_exam": [agent_a]
    }

    async def run_evaluation(self, exam_type: str, video_paths: list, api_key: str, job_id: str):
        agents = self.EXAM_CONFIG.get(exam_type, [agent_a]) # 預設至少跑 A
        
        # 使用 asyncio.gather 同時啟動多個 Agent
        tasks = [agent.evaluate(video_paths, api_key, job_id) for agent in agents]
        
        # 執行並等待所有 Agent 回傳結果
        results = await asyncio.gather(*tasks)
        
        # 整合結果 (這部分邏輯可以自定義)
        return self.aggregate(results)

    def aggregate(self, results):
        # 範例：合併所有 Checklist
        combined_checklist = []
        for r in results:
            combined_checklist.extend(r.get("checklist", []))
            
        return {
            "passed": all(item["passed"] for item in combined_checklist),
            "score": sum(r.get("score", 0) for r in results) / len(results),
            "checklist": combined_checklist,
            "details": " | ".join([r.get("details", "") for r in results])
        }

orchestrator = Orchestrator()
