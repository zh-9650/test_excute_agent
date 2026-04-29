import json
import base64
import uuid
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    id: str
    target_url: str
    username: str
    password: str
    storage_state: Optional[dict] = None
    created_at: float = 0.0
    last_used_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_used_at:
            self.last_used_at = time.time()


class SessionManager:
    def __init__(self, storage_dir: str = "data/sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionState] = {}

    def create(self, target_url: str, username: str, password: str) -> SessionState:
        sid = str(uuid.uuid4())[:8]
        encoded = base64.b64encode(password.encode()).decode()
        state = SessionState(
            id=sid, target_url=target_url,
            username=username, password=encoded
        )
        self._sessions[sid] = state
        return state

    def get_credentials(self, session_id: str) -> dict:
        state = self._sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        return {
            "username": state.username,
            "password": base64.b64decode(state.password.encode()).decode()
        }

    def save_storage_state(self, session_id: str, storage_state: dict):
        state = self._sessions[session_id]
        state.storage_state = storage_state
        state.last_used_at = time.time()
        path = self.storage_dir / f"{session_id}_state.json"
        path.write_text(json.dumps(storage_state, ensure_ascii=False))

    def load_storage_state(self, session_id: str) -> Optional[dict]:
        path = self.storage_dir / f"{session_id}_state.json"
        if path.exists():
            state = self._sessions.get(session_id)
            if state:
                state.last_used_at = time.time()
            return json.loads(path.read_text())
        return None

    def is_expired(self, state: SessionState, max_age_hours: int = 2) -> bool:
        return (time.time() - state.last_used_at) > max_age_hours * 3600

    def can_auto_relogin(self, state: SessionState) -> bool:
        return True
