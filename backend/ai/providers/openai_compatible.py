import json
import httpx
from backend.ai.base import AIResponse


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def analyze(self, system_prompt: str, user_prompt: str) -> AIResponse:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"}
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return AIResponse(
                judgment=parsed.get("judgment", "unknown"),
                confidence=parsed.get("confidence", 0.5),
                action=parsed.get("action", {}),
                reasoning=parsed.get("reasoning", ""),
                evidence=parsed.get("evidence", [])
            )

    async def generate_script(self, context: dict) -> str:
        system = "你是一个 Playwright 自动化测试工程师。请根据以下测试用例和元素地图生成 Python + Playwright 可执行脚本。"
        user = json.dumps(context, ensure_ascii=False)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "temperature": 0.2
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if "```python" in content:
                start = content.index("```python") + 10
                end = content.index("```", start)
                return content[start:end].strip()
            return content.strip()
