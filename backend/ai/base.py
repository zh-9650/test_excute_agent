from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class AIResponse:
    judgment: str
    confidence: float
    action: dict = field(default_factory=dict)
    reasoning: str = ""
    evidence: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    async def analyze(self, system_prompt: str, user_prompt: str) -> AIResponse:
        ...

    async def generate_script(self, context: dict) -> str:
        ...

    async def generate_structured_script(self, system_prompt: str, user_prompt: str) -> str:
        """结构化脚本生成 — 返回完整 Python 代码"""
        ...

    async def chat_with_tools(self, messages: list, tools: list) -> dict:
        """OpenAI function calling — 返回 {"tool_calls": [...], "content": "..."}
        """
        ...
