from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CaseStatus(str, Enum):
    PENDING = "pending"
    EXPLORING = "exploring"
    GENERATING = "generating"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ERROR = "error"


VALID_TRANSITIONS = {
    CaseStatus.PENDING: [CaseStatus.EXPLORING, CaseStatus.RUNNING],
    CaseStatus.EXPLORING: [CaseStatus.GENERATING, CaseStatus.BLOCKED, CaseStatus.RUNNING],
    CaseStatus.GENERATING: [CaseStatus.RUNNING, CaseStatus.ERROR],
    CaseStatus.RUNNING: [CaseStatus.PASSED, CaseStatus.FAILED, CaseStatus.BLOCKED, CaseStatus.ERROR],
    CaseStatus.PASSED: [CaseStatus.PENDING, CaseStatus.RUNNING],
    CaseStatus.FAILED: [CaseStatus.PENDING, CaseStatus.RUNNING],
    CaseStatus.BLOCKED: [CaseStatus.PENDING, CaseStatus.EXPLORING],
    CaseStatus.ERROR: [CaseStatus.PENDING, CaseStatus.RUNNING],
}


@dataclass
class Step:
    order: int
    action: str
    enrichment: Optional[dict] = None

    @property
    def is_enriched(self) -> bool:
        return self.enrichment is not None and "target_url" in (self.enrichment or {})

    @property
    def target_url(self) -> Optional[str]:
        return self.enrichment.get("target_url") if self.enrichment else None


@dataclass
class TestCase:
    __test__ = False  # 防止 pytest 收集此 dataclass

    id: str
    suite_id: str
    module: str
    title: str
    preconditions: str = ""
    steps: list[Step] = field(default_factory=list)
    expected: str = ""
    keywords: str = ""
    priority: int = 2
    test_type: str = "功能测试"
    stage: str = "系统测试阶段"
    status: CaseStatus = CaseStatus.PENDING
    completeness: str = "unknown"

    def transition_to(self, new_status: CaseStatus):
        if new_status not in VALID_TRANSITIONS.get(self.status, []):
            raise ValueError(f"Invalid transition: {self.status.value} -> {new_status.value}")
        self.status = new_status
