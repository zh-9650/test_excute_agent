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
