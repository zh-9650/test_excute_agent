import json
import httpx
from backend.ai.base import AIResponse


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _extract_content(self, data: dict) -> str:
        """从 API 响应中提取 content，处理 reasoning 模型 content 为空的情况"""
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content:
            # reasoning 模型可能把内容放在 reasoning_content
            reasoning = msg.get("reasoning_content") or ""
            if reasoning:
                # 尝试从 reasoning 中提取 JSON
                return reasoning
        return content

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
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            if not content:
                return AIResponse(
                    judgment="error",
                    confidence=0.0,
                    action={},
                    reasoning="AI returned empty content",
                    evidence=[]
                )
            parsed = json.loads(content)
            return AIResponse(
                judgment=parsed.get("judgment", "unknown"),
                confidence=parsed.get("confidence", 0.5),
                action=parsed.get("action", {}),
                reasoning=parsed.get("reasoning", ""),
                evidence=parsed.get("evidence", [])
            )

    async def observe(self, system_prompt: str, user_prompt: str) -> str:
        """观察分析 — 返回自由文本，不强制JSON格式"""
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
                    "max_tokens": 2000,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            return self._extract_content(data)

    async def explore_decide(self, system_prompt: str, user_prompt: str) -> dict:
        """探索决策 — 返回完整的 AI 决策字典（包含 action/selector/value/reasoning/confidence）"""
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
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"}
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            if not content:
                return {
                    "action": "wait",
                    "selector": "",
                    "value": "",
                    "reasoning": "AI returned empty content",
                    "confidence": 0.0,
                }
            parsed = json.loads(content)
            return {
                "action": parsed.get("action", "wait"),
                "selector": parsed.get("selector", ""),
                "value": parsed.get("value", ""),
                "reasoning": parsed.get("reasoning", ""),
                "confidence": parsed.get("confidence", 0.5),
            }

    async def generate_script(self, context: dict) -> str:
        system = """你是一个 Playwright 自动化测试工程师。请根据以下测试用例和元素地图生成 Python + Playwright 可执行脚本。

要求：
1. 脚本必须包含 `from playwright.async_api import async_playwright` 导入
2. 使用 `async def` 定义测试函数
3. 使用 page.goto(), page.click(), page.fill() 等 Playwright API
4. 只输出 Python 代码，不要包含解释文字
5. 如果无法确定选择器，使用 page.get_by_text() 或 page.get_by_role() 等语义定位器"""
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
                    "temperature": 0.2,
                    "max_tokens": 4000,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            if not content:
                return ""
            # 提取代码块
            if "```python" in content:
                start = content.index("```python") + 10
                end = content.index("```", start)
                return content[start:end].strip()
            elif "```" in content:
                start = content.index("```") + 3
                # 跳过可能的语言标识符
                newline = content.index("\n", start) if "\n" in content[start:start+10] else start
                end = content.index("```", newline)
                return content[newline:end].strip()
            return content.strip()

    async def generate_structured_script(self, system_prompt: str, user_prompt: str) -> str:
        """结构化脚本生成 — 返回完整 Python 代码，不要求 JSON 格式"""
        async with httpx.AsyncClient(timeout=180) as client:
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
                    "temperature": 0.2,
                    "max_tokens": 4000,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = self._extract_content(data)
            if not content:
                return ""
            # 提取代码块
            if "```python" in content:
                start = content.index("```python") + 10
                end = content.index("```", start)
                return content[start:end].strip()
            elif "```" in content:
                start = content.index("```") + 3
                newline = content.index("\n", start) if "\n" in content[start:start+10] else start
                end = content.index("```", newline)
                return content[newline:end].strip()
            return content.strip()

    async def chat_with_tools(self, messages: list, tools: list) -> dict:
        """OpenAI function calling — 返回 {"tool_calls": [...], "content": "..."}"""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "temperature": 0.3,
                    "max_tokens": 2000,
                }
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]

            tool_calls = []
            for tc in (msg.get("tool_calls") or []):
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    }
                })

            content = msg.get("content") or ""

            return {
                "tool_calls": tool_calls,
                "content": content,
            }
