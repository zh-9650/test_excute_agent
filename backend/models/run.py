from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RunStatus(str, Enum):
    PENDING = "pending"
    EXPLORING = "exploring"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


@dataclass
class TestRun:
    id: str
    suite_id: str
    target_url: str
    credentials: dict = field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    config: dict = field(default_factory=dict)
