from dataclasses import dataclass
from typing import Optional


@dataclass
class AICallRecord:
    id: str
    run_id: str
    case_id: str
    scenario: str
    model: str
    prompt: str
    response: str
    judgment: Optional[str] = None
    confidence: Optional[float] = None
    duration_ms: int = 0
    created_at: str = ""
