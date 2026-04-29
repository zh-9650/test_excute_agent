from dataclasses import dataclass
from typing import Optional


@dataclass
class HealingRecord:
    id: str
    original_selector: str
    healed_selector: str
    page_url_pattern: str
    context_signature: Optional[str] = None
    strategy: str = ""
    success_count: int = 1
    fail_count: int = 0
    last_used_at: str = ""
    created_at: str = ""
