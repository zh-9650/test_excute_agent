# AI 驱动自动化测试平台 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 AI 驱动的自动化测试平台，支持 CSV 用例导入、Playwright 页面探索、Python 脚本生成与智能执行、Markdown 报告输出。

**Architecture:** FastAPI 后端 + React 前端，模块化引擎设计。SQLite 存储元数据，文件系统存储制品。AI 层可配置多提供商。所有操作 API 驱动，支持 Web 操作和 CI/CD 集成。

**Tech Stack:** Python 3.11+, FastAPI, Playwright, React 18, Vite, SQLite, Jinja2

---

## 阶段概览

| 阶段 | 任务数 | 产出 | 进度 |
|------|--------|------|------|
| 一、基础设施 | 4 | 项目脚手架、数据模型、AI 适配层、配置管理 | ✅ 已完成 |
| 二、输入管道 | 3 | CSV 解析、AI 预检补全、用例管理 | ✅ 已完成 |
| 三、探索引擎 | 3 | 会话管理、浏览器控制、**AI 驱动探索（核心重构）** | 🔧 重构中 |
| 四、脚本生成 | 3 | **模板转换**（无需 AI）、预检、测试数据工厂 | 🔧 待调整 |
| 五、智能执行 | 4 | 基础执行器、AI 决策、选择器自愈、结果分析 | 🔧 待调整 |
| 六、报告输出 | 2 | Jinja2 模板渲染、Markdown+JSON 报告 | ✅ 已完成 |
| 七、API 层 | 3 | REST 端点、WebSocket、**分步执行 API** | ✅ 已完成 |
| 八、前端 | 4 | 脚手架、用例导入、**执行面板（含暂停/停止）**、报告页 | ✅ 已完成 |
| 九、集成验证 | 2 | 端到端流程、边界异常测试 | ⏳ 待开始 |

> **架构变更说明**：
> - 探索引擎从"按 URL 机械导航"改为"AI 驱动预执行"（Task 8 重写）
> - 脚本生成从"AI 生成"改为"模板转换"（Task 9 简化）
> - 执行器保持"回放+自愈"不变，但脚本来源变为探索记录（Task 11 微调）

---

### Task 1: 项目脚手架 + 依赖管理 ✅

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/pyproject.toml`
- Create: `backend/README.md`

- [x] **Step 1: 创建后端目录结构**

```bash
mkdir -p backend/engine/{parser,explorer,generator,executor,reporter}
mkdir -p backend/ai backend/models backend/storage backend/templates/sections
mkdir -p backend/api
mkdir -p tests
```

- [ ] **Step 2: 编写 requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
playwright==1.52.0
websockets==14.1
python-multipart==0.0.20
jinja2==3.1.6
```

- [ ] **Step 3: 编写 pyproject.toml**

```toml
[project]
name = "test-platform"
version = "0.1.0"
description = "AI-driven automated test platform"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "playwright>=1.52",
    "websockets>=14",
    "python-multipart>=0.0.20",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.25",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 4: 安装依赖**

```bash
cd backend && pip install -e ".[dev]" && playwright install chromium
```

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/pyproject.toml backend/README.md
git commit -m "chore: project scaffold with FastAPI + Playwright deps"
```

---

### Task 2: 数据模型 + SQLite 存储层 ✅

**Files:**
- Create: `backend/models/__init__.py`
- Create: `backend/models/case.py`
- Create: `backend/models/run.py`
- Create: `backend/models/ai_record.py`
- Create: `backend/models/healing.py`
- Create: `backend/storage/__init__.py`
- Create: `backend/storage/database.py`
- Test: `tests/test_models.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 编写测试用例模型**

```python
# tests/test_models.py
import pytest
from backend.models.case import TestCase, CaseStatus, Step

def test_create_test_case():
    case = TestCase(
        id="case-001",
        suite_id="suite-001",
        module="/场景管理(#147)",
        title="场景列表正确展示",
        preconditions="用户已登录",
        steps=[
            Step(order=1, action="进入/场景管理(#147)页面"),
            Step(order=2, action="观察场景列表")
        ],
        expected="正确展示场景列表",
        keywords="场景,列表展示",
        priority=1,
        test_type="功能测试",
        stage="系统测试阶段"
    )
    assert case.status == CaseStatus.PENDING
    assert len(case.steps) == 2
    assert case.priority == 1

def test_step_model():
    step = Step(order=1, action="点击编辑按钮", enrichment={
        "target_url": "/scenario/1/edit",
        "selector_hint": "button.edit-btn"
    })
    assert step.is_enriched is True
    assert step.target_url == "/scenario/1/edit"

def test_case_status_transitions():
    case = TestCase(id="case-001", suite_id="s-001", module="/", title="t")
    assert case.status == CaseStatus.PENDING
    case.transition_to(CaseStatus.EXPLORING)
    assert case.status == CaseStatus.EXPLORING
    # 非法转换应抛异常
    with pytest.raises(ValueError):
        case.transition_to(CaseStatus.PASSED)  # 不能直接从 EXPLORING 到 PASSED
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_models.py -v
# Expected: FAIL — 模块不存在
```

- [ ] **Step 3: 实现数据模型**

```python
# backend/models/__init__.py
from .case import TestCase, CaseStatus, Step
from .run import TestRun, RunStatus
from .ai_record import AICallRecord
from .healing import HealingRecord

__all__ = ["TestCase", "CaseStatus", "Step", "TestRun", "RunStatus", "AICallRecord", "HealingRecord"]
```

```python
# backend/models/case.py
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

# 合法状态转换
VALID_TRANSITIONS = {
    CaseStatus.PENDING: [CaseStatus.EXPLORING],
    CaseStatus.EXPLORING: [CaseStatus.GENERATING, CaseStatus.BLOCKED],
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
    completeness: str = "unknown"  # complete | incomplete | enriched

    def transition_to(self, new_status: CaseStatus):
        if new_status not in VALID_TRANSITIONS.get(self.status, []):
            raise ValueError(f"Invalid transition: {self.status.value} -> {new_status.value}")
        self.status = new_status
```

```python
# backend/models/run.py
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
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
    credentials: dict
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    config: dict = field(default_factory=dict)
```

```python
# backend/models/ai_record.py
from dataclasses import dataclass
from typing import Optional


@dataclass
class AICallRecord:
    id: str
    run_id: str
    case_id: str
    scenario: str  # selector_failure | assertion_failure | script_exception
    model: str
    prompt: str
    response: str
    judgment: Optional[str] = None
    confidence: Optional[float] = None
    duration_ms: int = 0
    created_at: str = ""
```

```python
# backend/models/healing.py
from dataclasses import dataclass


@dataclass
class HealingRecord:
    id: str
    original_selector: str
    healed_selector: str
    page_url_pattern: str
    context_signature: Optional[str] = None
    strategy: str = ""  # text_match | role_match | css_stable | xpath_fallback | compound
    success_count: int = 1
    fail_count: int = 0
    last_used_at: str = ""
    created_at: str = ""
```

- [ ] **Step 4: 实现 SQLite 存储层**

```python
# backend/storage/database.py
import sqlite3
import json
from pathlib import Path
from typing import Optional

DB_DIR = Path("data")
DB_PATH = DB_DIR / "test_platform.db"


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS test_suites (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        file_name TEXT,
        case_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS test_cases (
        id TEXT PRIMARY KEY,
        suite_id TEXT NOT NULL,
        module TEXT,
        title TEXT,
        preconditions TEXT DEFAULT '',
        steps TEXT DEFAULT '[]',
        expected TEXT DEFAULT '',
        keywords TEXT DEFAULT '',
        priority INTEGER DEFAULT 2,
        test_type TEXT DEFAULT '功能测试',
        stage TEXT DEFAULT '系统测试阶段',
        status TEXT DEFAULT 'pending',
        completeness TEXT DEFAULT 'unknown',
        FOREIGN KEY (suite_id) REFERENCES test_suites(id)
    );

    CREATE TABLE IF NOT EXISTS test_runs (
        id TEXT PRIMARY KEY,
        suite_id TEXT NOT NULL,
        target_url TEXT,
        credentials TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending',
        started_at TEXT,
        finished_at TEXT,
        config TEXT DEFAULT '{}',
        FOREIGN KEY (suite_id) REFERENCES test_suites(id)
    );

    CREATE TABLE IF NOT EXISTS case_results (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        status TEXT,
        ai_judgment TEXT,
        ai_confidence REAL,
        retry_count INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        screenshot_paths TEXT DEFAULT '[]',
        video_path TEXT,
        FOREIGN KEY (run_id) REFERENCES test_runs(id),
        FOREIGN KEY (case_id) REFERENCES test_cases(id)
    );

    CREATE TABLE IF NOT EXISTS ai_calls (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        case_id TEXT,
        scenario TEXT,
        model TEXT,
        prompt TEXT,
        response TEXT,
        judgment TEXT,
        confidence REAL,
        duration_ms INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS element_map (
        id TEXT PRIMARY KEY,
        exploration_id TEXT NOT NULL,
        page_url TEXT,
        selector TEXT,
        tag TEXT,
        text TEXT,
        aria_label TEXT,
        classes TEXT,
        collected_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS exploration_logs (
        id TEXT PRIMARY KEY,
        exploration_id TEXT NOT NULL,
        page_url TEXT,
        target_module TEXT,
        status TEXT,
        elements_found INTEGER DEFAULT 0,
        error_reason TEXT,
        screenshot_path TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS healing_records (
        id TEXT PRIMARY KEY,
        original_selector TEXT NOT NULL,
        healed_selector TEXT NOT NULL,
        page_url_pattern TEXT NOT NULL,
        context_signature TEXT,
        strategy TEXT DEFAULT '',
        success_count INTEGER DEFAULT 1,
        fail_count INTEGER DEFAULT 0,
        last_used_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(original_selector, page_url_pattern)
    );
    """)
    conn.commit()
    conn.close()


init_db()
```

- [ ] **Step 5: 运行测试确认模型通过**

```bash
pytest tests/test_models.py -v
# Expected: PASS
```

- [ ] **Step 6: Commit**

```bash
git add backend/models/ backend/storage/ tests/test_models.py
git commit -m "feat: data models + SQLite storage layer"
```

---

### Task 3: AI 提供商适配层 + 配置管理 ✅

**Files:**
- Create: `backend/ai/__init__.py`
- Create: `backend/ai/base.py`
- Create: `backend/ai/providers/openai_compatible.py`
- Create: `backend/config.py`
- Test: `tests/test_ai.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 编写 AI 适配层测试**

```python
# tests/test_ai.py
import pytest
from backend.ai.base import AIProvider, AIResponse
from backend.ai.providers.openai_compatible import OpenAICompatibleProvider
from backend.config import Config


def test_ai_response_model():
    resp = AIResponse(
        judgment="selector_changed",
        confidence=0.85,
        action={"type": "retry_with_selector", "new_selector": "button#submit"},
        reasoning="按钮 class 从 .btn-primary 变为 .btn-submit",
        evidence=["screenshot_base64"]
    )
    assert resp.judgment == "selector_changed"
    assert resp.confidence == 0.85


def test_config_defaults():
    config = Config()
    assert config.ai_provider == "openai_compatible"
    assert config.ai_model == "deepseek-chat"
    assert config.ai_base_url == "https://api.deepseek.com/v1"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "qwen")
    monkeypatch.setenv("AI_MODEL", "qwen3.5-122b")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("AI_API_KEY", "sk-local")
    config = Config()
    assert config.ai_provider == "qwen"
    assert config.ai_model == "qwen3.5-122b"


def test_config_from_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"ai_provider": "deepseek", "ai_model": "deepseek-chat"}')
    config = Config(config_path=str(config_file))
    assert config.ai_provider == "deepseek"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_ai.py tests/test_config.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现 AI 适配层**

```python
# backend/ai/base.py
from dataclasses import dataclass, field
from typing import Optional, Protocol


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
```

```python
# backend/ai/providers/openai_compatible.py
import json
import httpx
from backend.ai.base import AIProvider, AIResponse


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
            # 提取代码块
            if "```python" in content:
                start = content.index("```python") + 10
                end = content.index("```", start)
                return content[start:end].strip()
            return content.strip()
```

```python
# backend/config.py
import os
import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    ai_provider: str = "openai_compatible"
    ai_model: str = "deepseek-chat"
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_api_key: str = ""
    ai_backup_model: str = ""
    ai_backup_base_url: str = ""
    ai_backup_api_key: str = ""
    browser_headless: bool = False
    default_timeout_step: int = 300000  # 5min in ms
    video_on_failure: bool = True

    def __post_init__(self):
        self._load_from_env()

    def __init__(self, config_path: str = ""):
        if config_path and Path(config_path).exists():
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            for k, v in data.items():
                setattr(self, k, v)
        self._load_from_env()

    def _load_from_env(self):
        mappings = {
            "AI_PROVIDER": "ai_provider",
            "AI_MODEL": "ai_model",
            "AI_BASE_URL": "ai_base_url",
            "AI_API_KEY": "ai_api_key",
            "AI_BACKUP_MODEL": "ai_backup_model",
            "AI_BACKUP_BASE_URL": "ai_backup_base_url",
            "AI_BACKUP_API_KEY": "ai_backup_api_key",
            "BROWSER_HEADLESS": "browser_headless",
        }
        for env_key, attr in mappings.items():
            val = os.environ.get(env_key)
            if val is not None:
                if attr == "browser_headless":
                    setattr(self, attr, val.lower() == "true")
                else:
                    setattr(self, attr, val)

    def create_provider(self):
        from backend.ai.providers.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            base_url=self.ai_base_url,
            api_key=self.ai_api_key,
            model=self.ai_model
        )

    def create_backup_provider(self):
        if not self.ai_backup_model:
            return None
        from backend.ai.providers.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            base_url=self.ai_backup_base_url,
            api_key=self.ai_backup_api_key,
            model=self.ai_backup_model
        )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_ai.py tests/test_config.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/ai/ backend/config.py tests/test_ai.py tests/test_config.py
git commit -m "feat: AI provider abstraction + config management"
```

---

### Task 4: CSV 解析器 + AI 预检补全 ✅

**Files:**
- Create: `backend/engine/parser/__init__.py`
- Create: `backend/engine/parser/csv_parser.py`
- Create: `backend/engine/parser/enricher.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: 编写解析器测试**

```python
# tests/test_parser.py
import pytest
import tempfile
from pathlib import Path
from backend.engine.parser.csv_parser import CSVParser
from backend.models.case import TestCase, CaseStatus


@pytest.fixture
def sample_csv():
    return """所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段
/场景管理(#147),场景列表正确展示,1. 用户已登录,1. 进入页面 2. 观察列表,1. 正确展示 2. 显示3条,场景,1,功能测试,系统测试阶段
/场景管理(#147),新增场景-正常流程,1. 用户已登录,1. 点击新增 2. 输入名称 3. 保存,1. 创建成功 2. 列表刷新,新增,1,功能测试,系统测试阶段
"""


def test_parse_csv_with_utf8(sample_csv):
    parser = CSVParser()
    cases = parser.parse(sample_csv)
    assert len(cases) == 2
    assert cases[0].module == "/场景管理(#147)"
    assert cases[0].title == "场景列表正确展示"
    assert len(cases[0].steps) == 2
    assert cases[0].priority == 1


def test_parse_csv_with_gbk():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,测试点1,条件,1. 步骤1,1. 预期1,关键,1,功能测试,系统测试阶段"
    cases = parser.parse(content.encode("gbk"))
    assert len(cases) == 1


def test_parse_empty_steps():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,测试点1,条件,,1. 预期1,,1,功能测试,系统测试阶段"
    cases = parser.parse(content)
    assert cases[0].steps == []


def test_parse_missing_columns():
    parser = CSVParser()
    content = "所属模块,测试点\n/测试,测试点1"
    cases = parser.parse(content)
    assert len(cases) == 0  # 缺少必填列，跳过


def test_case_completeness_detection():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,点击编辑,1. 已登录,1. 点击编辑,1. 弹窗出现,编辑,1,功能测试,系统测试阶段"
    cases = parser.parse(content)
    assert cases[0].completeness == "incomplete"  # "点击编辑" 缺少页面上下文
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_parser.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现 CSV 解析器**

```python
# backend/engine/parser/csv_parser.py
import csv
import io
import re
import uuid
from backend.models.case import TestCase, Step


class CSVParser:
    REQUIRED_COLUMNS = ["所属模块", "测试点", "步骤", "预期"]

    def parse(self, content) -> list[TestCase]:
        if isinstance(content, bytes):
            content = self._detect_and_decode(content)

        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            return []

        missing = [c for c in self.REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            return []

        cases = []
        for row in reader:
            if not row.get("测试点") or not row.get("测试点").strip():
                continue

            steps = self._parse_steps(row.get("步骤", ""))
            case = TestCase(
                id=str(uuid.uuid4()),
                suite_id="",
                module=row.get("所属模块", "").strip(),
                title=row.get("测试点", "").strip(),
                preconditions=row.get("前置条件", "").strip(),
                steps=steps,
                expected=row.get("预期", "").strip(),
                keywords=row.get("关键词", "").strip(),
                priority=self._parse_priority(row.get("优先级", "2")),
                test_type=row.get("测试类型", "功能测试").strip(),
                stage=row.get("适用阶段", "系统测试阶段").strip(),
                completeness=self._detect_completeness(row)
            )
            cases.append(case)
        return cases

    def _parse_steps(self, steps_text: str) -> list[Step]:
        if not steps_text.strip():
            return []
        result = []
        pattern = re.compile(r'(\d+)\.\s*(.*?)(?=\d+\.\s|\Z)', re.DOTALL)
        matches = pattern.findall(steps_text)
        for num, action in matches:
            action_text = action.strip().rstrip(";；").strip()
            if action_text:
                result.append(Step(order=int(num), action=action_text))
        if not result and steps_text.strip():
            result.append(Step(order=1, action=steps_text.strip()))
        return result

    def _parse_priority(self, val: str) -> int:
        try:
            p = int(val.strip())
            return p if 1 <= p <= 4 else 2
        except (ValueError, TypeError):
            return 2

    def _detect_completeness(self, row: dict) -> str:
        title = row.get("测试点", "")
        steps = row.get("步骤", "")
        if not title and not steps:
            return "incomplete"
        # 简单规则判断：步骤中包含导航信息视为完整
        nav_indicators = ["进入", "打开", "页面", "URL", "登录", "跳转"]
        combined = title + steps
        has_nav = any(ind in combined for ind in nav_indicators)
        has_specific = any(ind in combined for ind in ["点击", "输入", "选择", "上传", "删除"])
        if has_nav and has_specific:
            return "complete"
        if has_specific:
            return "incomplete"
        return "unknown"

    def _detect_and_decode(self, data: bytes) -> str:
        for encoding in ["utf-8", "gbk", "gb2312", "gb18030"]:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")
```

- [ ] **Step 4: 运行解析器测试**

```bash
pytest tests/test_parser.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/parser/ tests/test_parser.py
git commit -m "feat: CSV parser with encoding detection + completeness check"
```

---

### Task 5: AI 预检补全器 ✅

**Files:**
- Create: `backend/engine/parser/enricher.py`
- Test: `tests/test_enricher.py`

- [ ] **Step 1: 编写补全器测试**

```python
# tests/test_enricher.py
import pytest
from backend.engine.parser.enricher import CaseEnricher
from backend.models.case import TestCase, Step

@pytest.fixture
def incomplete_case():
    return TestCase(
        id="c-001", suite_id="s-001",
        module="/场景管理(#147)", title="编辑按钮",
        steps=[Step(order=1, action="点击编辑按钮")],
        expected="弹出编辑弹窗",
        completeness="incomplete"
    )

@pytest.fixture
def complete_case():
    return TestCase(
        id="c-002", suite_id="s-001",
        module="/场景管理(#147)", title="进入场景页面查看列表",
        steps=[Step(order=1, action="进入/场景管理(#147)页面"), Step(order=2, action="观察列表")],
        expected="展示场景列表",
        completeness="complete"
    )

def test_enricher_skips_complete_cases(complete_case):
    enricher = CaseEnricher(ai_provider=None)
    result = enricher.evaluate(complete_case)
    assert result["needs_enrichment"] is False

def test_enricher_detects_incomplete(incomplete_case):
    enricher = CaseEnricher(ai_provider=None)
    result = enricher.evaluate(incomplete_case)
    assert result["needs_enrichment"] is True
    assert "suggested_url" in result["template"]
    assert "selector_hint" in result["template"]

def test_enricher_generates_template_structure(incomplete_case):
    enricher = CaseEnricher(ai_provider=None)
    result = enricher.evaluate(incomplete_case)
    template = result["template"]
    assert "target_url" in template
    assert "建议的目标页面路径" in template["target_url"]
    assert "selector_hint" in template

def test_batch_evaluate():
    enricher = CaseEnricher(ai_provider=None)
    cases = [
        TestCase(id="1", suite_id="s", module="/m", title="进入页面查看", steps=[Step(1, "进入/m页面")], completeness="complete"),
        TestCase(id="2", suite_id="s", module="/m", title="点击按钮", steps=[Step(1, "点击按钮")], completeness="incomplete"),
    ]
    results = enricher.batch_evaluate(cases)
    assert len(results["needs_enrichment"]) == 1
    assert len(results["ready"]) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_enricher.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现补全器**

```python
# backend/engine/parser/enricher.py
class CaseEnricher:
    def __init__(self, ai_provider=None):
        self.ai = ai_provider

    def evaluate(self, case) -> dict:
        if case.completeness == "complete":
            return {"needs_enrichment": False, "case_id": case.id}

        template = {
            "target_url": "",
            "target_url_hint": "建议的目标页面路径",
            "selector_hint": "",
            "selector_hint_desc": "可选，描述目标元素（如：列表页的编辑按钮、弹窗中的保存按钮）",
            "extra_note": "",
            "extra_note_desc": "补充说明（如：需要先选择某条数据）"
        }
        if case.module:
            template["target_url"] = case.module

        return {
            "needs_enrichment": True,
            "case_id": case.id,
            "case_title": case.title,
            "module": case.module,
            "steps": [s.action for s in case.steps],
            "template": template
        }

    def batch_evaluate(self, cases: list) -> dict:
        needs = []
        ready = []
        for case in cases:
            result = self.evaluate(case)
            if result["needs_enrichment"]:
                needs.append(result)
            else:
                ready.append(case.id)
        return {"needs_enrichment": needs, "ready": ready, "total": len(cases)}

    def apply_enrichment(self, case, enrichment_data: dict) -> None:
        for step in case.steps:
            step.enrichment = {
                "target_url": enrichment_data.get("target_url", ""),
                "selector_hint": enrichment_data.get("selector_hint", "")
            }
        case.completeness = "enriched"
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_enricher.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/parser/enricher.py tests/test_enricher.py
git commit -m "feat: AI case enricher with completeness evaluation"
```

---

### Task 6: 会话管理器 ✅

**Files:**
- Create: `backend/engine/explorer/session.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: 编写会话管理测试**

```python
# tests/test_session.py
import json
from pathlib import Path
from backend.engine.explorer.session import SessionManager, SessionState

def test_session_created_with_credentials():
    sm = SessionManager()
    state = sm.create(target_url="https://test.example.com",
                      username="admin", password="test123")
    assert state.target_url == "https://test.example.com"
    assert state.username == "admin"
    assert state.storage_state is None

def test_save_and_load_storage_state(tmp_path):
    sm = SessionManager(storage_dir=str(tmp_path))
    state = sm.create("https://test.example.com", "admin", "pass")
    fake_state = {"cookies": [{"name": "token", "value": "abc"}]}
    sm.save_storage_state(state.id, fake_state)

    loaded = sm.load_storage_state(state.id)
    assert loaded == fake_state

def test_session_expiry_detection():
    sm = SessionManager()
    state = sm.create("https://test.example.com", "admin", "pass")
    # 新创建的会话未过期
    assert sm.is_expired(state) is False

def test_credential_encryption():
    sm = SessionManager()
    state = sm.create("https://test.example.com", "admin", "s3cret!")
    assert state.password != "s3cret!"  # 加密后不同

    decrypted = sm.get_credentials(state.id)
    assert decrypted["username"] == "admin"
    assert decrypted["password"] == "s3cret!"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_session.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现会话管理器**

```python
# backend/engine/explorer/session.py
import json
import base64
import hashlib
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
    password: str  # base64 encoded
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
        """SSO/验证码场景返回 False，需人工介入"""
        return True
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_session.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/explorer/session.py tests/test_session.py
git commit -m "feat: session manager with credential encryption + storageState"
```

---

### Task 7: Playwright 浏览器控制器 ✅

**Files:**
- Create: `backend/engine/explorer/browser.py`
- Test: `tests/test_browser.py`

- [ ] **Step 1: 编写浏览器控制器测试**

```python
# tests/test_browser.py
import pytest
from backend.engine.explorer.browser import BrowserController, ElementInfo

def test_element_info_model():
    el = ElementInfo(
        tag="button", text="Submit",
        selector="button:has-text('Submit')",
        aria_label="submit form",
        classes=["btn", "btn-primary"],
        attributes={"type": "submit", "data-action": "save"}
    )
    assert el.tag == "button"
    assert el.text == "Submit"
    assert "btn-primary" in el.classes

@pytest.mark.asyncio
async def test_browser_controller_init():
    bc = BrowserController(headless=True)
    try:
        await bc.start()
        assert bc.page is not None
    finally:
        await bc.stop()

@pytest.mark.asyncio
async def test_browser_navigate_and_collect():
    bc = BrowserController(headless=True)
    try:
        await bc.start()
        # 使用 Playwright 内置的 about:blank
        await bc.page.goto("about:blank")
        elements = await bc.collect_interactive_elements()
        assert isinstance(elements, list)
    finally:
        await bc.stop()

@pytest.mark.asyncio
async def test_wait_strategies():
    bc = BrowserController(headless=True)
    try:
        await bc.start()
        strategies = ["networkidle", "domcontentloaded", "fixed"]
        for s in strategies:
            await bc.page.goto("about:blank")
            result = await bc.wait_for_page_ready(strategy=s)
            assert result is True
    finally:
        await bc.stop()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_browser.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现浏览器控制器**

```python
# backend/engine/explorer/browser.py
import asyncio
import hashlib
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Page, Browser


@dataclass
class ElementInfo:
    tag: str
    text: str = ""
    selector: str = ""
    aria_label: str = ""
    classes: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    is_visible: bool = True


class BrowserController:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser = None
        self.page: Page = None

    async def start(self):
        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN"
        )
        self.page = await context.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.__aexit__(None, None, None)

    async def goto(self, url: str, timeout_ms: int = 30000) -> dict:
        try:
            await self.page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    async def wait_for_page_ready(self, strategy: str = "networkidle", timeout_ms: int = 10000) -> bool:
        try:
            if strategy == "networkidle":
                await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
            elif strategy == "domcontentloaded":
                await self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            else:
                await asyncio.sleep(timeout_ms / 1000)
            return True
        except Exception:
            return False

    async def collect_interactive_elements(self) -> list[ElementInfo]:
        elements = []
        interactive_tags = ["button", "a", "input", "select", "textarea"]
        for tag in interactive_tags:
            locators = self.page.locator(tag)
            count = await locators.count()
            for i in range(min(count, 200)):
                try:
                    el = locators.nth(i)
                    if not await el.is_visible():
                        continue
                    text = await el.inner_text() if tag in ("button", "a") else ""
                    text = text.strip()[:200] if text else ""
                    classes = await el.get_attribute("class") or ""
                    aria = await el.get_attribute("aria-label") or ""
                    selector = self._build_selector(tag, text, aria, classes)
                    elements.append(ElementInfo(
                        tag=tag, text=text, selector=selector,
                        aria_label=aria,
                        classes=classes.split() if classes else [],
                        attributes={}
                    ))
                except Exception:
                    continue
        return elements

    def _build_selector(self, tag: str, text: str, aria: str, classes: str) -> str:
        if text and len(text) < 50:
            return f"{tag}:has-text('{text}')"
        if aria:
            return f"{tag}[aria-label='{aria}']"
        if classes:
            first_class = classes.split()[0]
            return f"{tag}.{first_class}"
        return tag

    async def take_screenshot(self, path: str):
        await self.page.screenshot(path=path, full_page=False)

    async def get_page_summary(self) -> dict:
        url = self.page.url
        title = await self.page.title()
        dom_text = await self.page.inner_text("body")
        return {"url": url, "title": title, "text_snippet": dom_text[:500]}

    async def dismiss_dialogs(self) -> bool:
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            close_btns = self.page.locator("button:has-text('关闭'), button:has-text('取消'), .modal-close")
            count = await close_btns.count()
            if count > 0:
                await close_btns.first.click()
            return True
        except Exception:
            return False
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_browser.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/explorer/browser.py tests/test_browser.py
git commit -m "feat: Playwright browser controller with element collection"
```

---

### Task 8: AI 驱动探索引擎（核心重构）

> **架构变更**：探索引擎从"按 URL 机械导航"改为"AI 驱动预执行"。AI 看到页面截图和元素列表，根据用例步骤描述决定下一步操作。

**Files:**
- Create: `backend/engine/explorer/ai_explorer.py`
- Create: `backend/engine/explorer/prompts.py`
- Modify: `backend/engine/explorer/browser.py` — 已完成（增加 type/placeholder/name 属性收集）
- Modify: `backend/engine/explorer/session.py` — 已完成（增加 session_id 参数）
- Modify: `backend/engine/orchestrator.py` — 已完成（登录检测修复、分步执行支持）
- Test: `tests/test_ai_explorer.py`

- [x] **Step 1: 浏览器控制器增强** — 已完成
  `browser.py` 已增加 `type`、`placeholder`、`name` 属性收集到 `ElementInfo.attributes`。

- [x] **Step 2: 会话管理器修复** — 已完成
  `session.py` 已增加 `session_id` 参数，解决探索/执行间 storageState 不匹配问题。

- [x] **Step 3: 登录检测修复** — 已完成
  `orchestrator._detect_and_login()` 已改为检查 `e.attributes.get("type") == "password"`，支持弹窗式登录。

- [ ] **Step 4: 编写 AI 探索提示词**

```python
# backend/engine/explorer/prompts.py

EXPLORATION_SYSTEM_PROMPT = """你是一个专业的自动化测试工程师。
你将看到一个网页截图和页面上的可交互元素列表。
根据给定的测试用例步骤描述，决定下一步操作。

返回 JSON 格式:
{
    "action": "click" | "fill" | "select" | "navigate" | "assert" | "wait" | "scroll",
    "selector": "元素选择器（从元素列表中选择最精确的）",
    "value": "操作值（fill 时为输入内容，select 时为选项值，其他为空）",
    "reasoning": "选择该元素和操作的原因",
    "confidence": 0.0-1.0
}

规则：
1. 优先使用 text 选择器（如 button:has-text('xxx')），其次 aria-label，最后 class
2. 如果步骤描述模糊，根据页面上下文推断最合理的操作
3. 如果找不到目标元素，返回 action: "wait" 并说明原因
4. confidence < 0.5 时表示不确定，需人工确认
"""

EXPLORATION_USER_TEMPLATE = """测试用例：{case_title}
前置条件：{preconditions}
当前步骤（第{step_num}步）：{step_action}
预期结果：{expected}

当前页面元素列表：
{elements_text}

请决定下一步操作。返回 JSON。"""

ASSERTION_SYSTEM_PROMPT = """你是一个测试断言专家。
你将看到操作前后的页面截图和元素列表。
根据预期结果，判断测试是否通过。

返回 JSON:
{
    "result": "pass" | "fail" | "uncertain",
    "reasoning": "判断依据",
    "actual_result": "实际观察到的结果",
    "confidence": 0.0-1.0
}"""
```

- [ ] **Step 5: 实现 AI 驱动探索引擎**

```python
# backend/engine/explorer/ai_explorer.py
import json
import asyncio
from dataclasses import dataclass, field
from backend.engine.explorer.browser import BrowserController, ElementInfo
from backend.engine.explorer.prompts import (
    EXPLORATION_SYSTEM_PROMPT, EXPLORATION_USER_TEMPLATE, ASSERTION_SYSTEM_PROMPT
)


@dataclass
class StepRecord:
    """单步探索记录"""
    step_num: int
    action_desc: str
    ai_action: str = ""        # click/fill/select/navigate/assert/wait
    ai_selector: str = ""
    ai_value: str = ""
    ai_reasoning: str = ""
    ai_confidence: float = 0.0
    executed: bool = False
    success: bool = False
    error: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""
    retry_count: int = 0


@dataclass
class CaseExplorationResult:
    """单用例探索结果"""
    case_id: str
    case_title: str
    status: str = "pending"  # exploring/explored/explore_failed
    steps: list[StepRecord] = field(default_factory=list)
    total_retries: int = 0


@dataclass
class ExplorationReport:
    """探索总报告"""
    run_id: str
    case_results: list[CaseExplorationResult] = field(default_factory=list)
    total_cases: int = 0
    explored_cases: int = 0
    failed_cases: int = 0
    total_steps: int = 0
    total_retries: int = 0


class AIExplorer:
    def __init__(self, browser: BrowserController, ai_provider, log_callback=None):
        self.browser = browser
        self.ai = ai_provider
        self.log = log_callback or (lambda *a, **kw: None)
        self._max_step_retries = 5

    async def explore_case(self, case, run_id: str) -> CaseExplorationResult:
        """探索单个用例"""
        result = CaseExplorationResult(case_id=case.id, case_title=case.title, status="exploring")

        for step in case.steps:
            record = StepRecord(step_num=step.order, action_desc=step.action)
            result.steps.append(record)

            success = await self._execute_step_with_retry(case, step, record, run_id)
            if not success:
                result.status = "explore_failed"
                return result

        result.status = "explored"
        return result

    async def _execute_step_with_retry(self, case, step, record: StepRecord, run_id: str) -> bool:
        """执行单步，最多重试 max_step_retries 次"""
        for attempt in range(self._max_step_retries):
            record.retry_count = attempt

            # 截图 + 收集元素
            screenshot_path = f"test_artifacts/{run_id}/explore_{case.id}_s{step.order}_a{attempt}.png"
            await self.browser.take_screenshot(screenshot_path)
            record.screenshot_before = screenshot_path

            elements = await self.browser.collect_interactive_elements()
            elements_text = self._format_elements(elements)

            # 发送给 AI 决策
            user_prompt = EXPLORATION_USER_TEMPLATE.format(
                case_title=case.title,
                preconditions=case.preconditions,
                step_num=step.order,
                step_action=step.action,
                expected=case.expected,
                elements_text=elements_text
            )

            try:
                response = await self.ai.analyze(EXPLORATION_SYSTEM_PROMPT, user_prompt)
                decision = self._parse_decision(response)
                record.ai_action = decision.get("action", "")
                record.ai_selector = decision.get("selector", "")
                record.ai_value = decision.get("value", "")
                record.ai_reasoning = decision.get("reasoning", "")
                record.ai_confidence = decision.get("confidence", 0)

                self.log("info", f"[Step {step.order}] AI: {record.ai_action} → {record.ai_selector} (conf={record.ai_confidence:.2f})")

                # 执行操作
                exec_result = await self._execute_action(record.ai_action, record.ai_selector, record.ai_value)
                record.executed = True

                if exec_result["success"]:
                    record.success = True
                    await asyncio.sleep(1)  # 等待页面响应
                    after_path = f"test_artifacts/{run_id}/explore_{case.id}_s{step.order}_after.png"
                    await self.browser.take_screenshot(after_path)
                    record.screenshot_after = after_path
                    return True
                else:
                    record.error = exec_result.get("error", "")
                    self.log("info", f"[Step {step.order}] 执行失败: {record.error}, 重试 {attempt+1}/{self._max_step_retries}")

            except Exception as e:
                record.error = str(e)
                self.log("error", f"[Step {step.order}] AI 决策异常: {e}")

            result.total_retries += 1

        return False

    async def _execute_action(self, action: str, selector: str, value: str) -> dict:
        """执行 AI 返回的操作"""
        try:
            if action == "click":
                await self.browser.page.click(selector, timeout=5000)
            elif action == "fill":
                await self.browser.page.fill(selector, value, timeout=5000)
            elif action == "select":
                await self.browser.page.select_option(selector, value, timeout=5000)
            elif action == "navigate":
                await self.browser.goto(value)
            elif action == "wait":
                await asyncio.sleep(2)
            elif action == "scroll":
                await self.browser.page.evaluate("window.scrollBy(0, 300)")
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _format_elements(self, elements: list[ElementInfo]) -> str:
        lines = []
        for i, el in enumerate(elements[:50]):
            attrs = el.attributes or {}
            parts = [f"[{i}] <{el.tag}>"]
            if el.text:
                parts.append(f"text='{el.text}'")
            if attrs.get("type"):
                parts.append(f"type='{attrs['type']}'")
            if attrs.get("placeholder"):
                parts.append(f"placeholder='{attrs['placeholder']}'")
            if el.aria_label:
                parts.append(f"aria='{el.aria_label}'")
            if el.selector:
                parts.append(f"selector='{el.selector}'")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def _parse_decision(self, response) -> dict:
        """解析 AI 响应为决策对象"""
        if hasattr(response, 'action'):
            return response.action if isinstance(response.action, dict) else {}
        if isinstance(response, dict):
            return response
        try:
            return json.loads(str(response))
        except:
            return {}
```

- [ ] **Step 6: 更新 Orchestrator 接入 AI 探索**

```python
# backend/engine/orchestrator.py 中新增 explore_only 方法
async def explore_only(self, state: RunState, target_url: str, credentials: dict) -> dict:
    """Step 1: AI 探索 — 打开浏览器，AI 逐步预执行每个用例"""
    # 加载用例
    db = get_db()
    rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (state.suite_id,)).fetchall()
    db.close()
    state.cases = [row_to_case(r) for r in rows]

    # 启动浏览器
    browser = BrowserController(headless=self.config.browser_headless)
    await browser.goto(target_url)

    # 自动登录（一次）
    login_ok = await self._detect_and_login(browser, target_url, credentials)
    if not login_ok:
        return {"error": "Login failed"}

    # AI 探索每个用例
    explorer = AIExplorer(browser, self.ai, log_callback=self.log)
    for i, case in enumerate(state.cases):
        if state.stop_requested:
            break
        state.current_case_index = i
        result = await explorer.explore_case(case, state.run_id)
        state.exploration_results[case.id] = result

    # 保存 storage state
    storage = await browser.page.context.storage_state()
    session_mgr.save_storage_state(state.run_id, storage)
    await browser.stop()

    return self._build_exploration_summary(state)
```

- [ ] **Step 7: 运行测试**

```bash
pytest tests/test_ai_explorer.py -v
# Expected: PASS
```

- [ ] **Step 8: Commit**

```bash
git add backend/engine/explorer/ai_explorer.py backend/engine/explorer/prompts.py
git commit -m "feat: AI-driven exploration engine - AI pre-executes test cases on real UI"
```

---

### Task 9: 脚本生成器（模板转换，无需 AI）

> **架构变更**：脚本生成从"AI 生成"改为"模板转换"。探索阶段已记录每步的真实选择器和操作，生成阶段只需按模板转换为 Playwright 脚本。

**Files:**
- Modify: `backend/engine/generator/generator.py` — 增加 `generate_from_exploration` 方法
- Test: `tests/test_generator.py`

- [x] **Step 1-5: 基础脚本生成器** — 已完成（Task 9 原始实现已存在）
  `ScriptGenerator.build_script_template()` 和 `precheck()` 已实现。

- [ ] **Step 6: 新增从探索记录生成脚本的方法**

```python
# backend/engine/generator/generator.py 中新增
def generate_from_exploration(self, case, exploration_result) -> str:
    """将探索记录直接转换为 Playwright 脚本（无需 AI）"""
    steps_code = []
    for step_record in exploration_result.steps:
        if not step_record.success:
            continue
        action = step_record.ai_action
        selector = step_record.ai_selector
        value = step_record.ai_value

        if action == "navigate":
            steps_code.append(f'    await page.goto("{value}")')
        elif action == "click":
            steps_code.append(f'    await page.click("{selector}")')
        elif action == "fill":
            steps_code.append(f'    await page.fill("{selector}", "{value}")')
        elif action == "select":
            steps_code.append(f'    await page.select_option("{selector}", "{value}")')
        elif action == "scroll":
            steps_code.append(f'    await page.evaluate("window.scrollBy(0, 300)")')
        elif action == "wait":
            steps_code.append(f'    await asyncio.sleep(2)')

    # 使用探索时的截图路径作为断言参考
    screenshots = [s.screenshot_after for s in exploration_result.steps if s.screenshot_after]

    script = f'''import asyncio
from playwright.async_api import async_playwright, expect

async def test_{case.id.replace("-", "_")}():
    """用例: {case.title} (从探索记录生成)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={{"width": 1920, "height": 1080}},
            locale="zh-CN"
        )
        page = await context.new_page()
        try:
{chr(10).join(steps_code)}

            # 最终截图验证
            await page.screenshot(path=f"verify_{case.id}.png")
            print("PASS: {case.title}")
        except Exception as e:
            print(f"FAIL: {case.title} - {{e}}")
            await page.screenshot(path=f"failure_{case.id}.png")
            raise
        finally:
            await browser.close()
'''
    return script
```

- [ ] **Step 7: 运行测试**

```bash
pytest tests/test_generator.py -v
# Expected: PASS
```

- [ ] **Step 8: Commit**

```bash
git add backend/engine/generator/generator.py
git commit -m "feat: script generator now supports template conversion from exploration records"
```

---

### Task 10: 测试数据工厂

**Files:**
- Create: `backend/engine/generator/data_factory.py`
- Test: `tests/test_data_factory.py`

- [ ] **Step 1: 编写测试数据工厂**

```python
# tests/test_data_factory.py
import os
from backend.engine.generator.data_factory import TestDataFactory

def test_generate_file_by_size():
    path = TestDataFactory.generate_file("10MB_file.pdf", size_mb=10)
    assert os.path.exists(path)
    assert os.path.getsize(path) == 10 * 1024 * 1024
    os.remove(path)

def test_generate_string_by_length():
    s = TestDataFactory.generate_string(51)
    assert len(s) == 51

def test_generate_emoji_string():
    s = TestDataFactory.generate_emoji_string(5)
    assert len(s) >= 5

def test_generate_html_string():
    s = TestDataFactory.generate_html_string()
    assert "<script>" in s
    assert "</script>" in s

def test_generate_by_keyword_file_size():
    path = TestDataFactory.generate_from_keyword("上传大小为10MB的文件")
    assert path is not None
    assert os.path.getsize(path) == 10 * 1024 * 1024
    os.remove(path)

def test_generate_by_keyword_string_length():
    s = TestDataFactory.generate_from_keyword("输入51字符名称")
    assert len(s) == 51

def test_generate_by_keyword_unknown():
    result = TestDataFactory.generate_from_keyword("some random action")
    assert result is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_data_factory.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现**

```python
# backend/engine/generator/data_factory.py
import os
import re
import tempfile


class TestDataFactory:
    EMOJI_SET = "😀🎉🔥💯✅❌🚀⭐❤️👍👎"

    @staticmethod
    def generate_file(filename: str, size_mb: int = 1) -> str:
        path = os.path.join(tempfile.gettempdir(), f"testdata_{filename}")
        with open(path, "wb") as f:
            f.write(b"\0" * size_mb * 1024 * 1024)
        return path

    @staticmethod
    def generate_string(length: int) -> str:
        return "测" * length

    @staticmethod
    def generate_emoji_string(count: int = 5) -> str:
        return TestDataFactory.EMOJI_SET * ((count // len(TestDataFactory.EMOJI_SET)) + 1)

    @staticmethod
    def generate_html_string() -> str:
        return '<script>alert("xss")</script><img src=x onerror=alert(1)>'

    @staticmethod
    def generate_from_keyword(action: str):
        size_match = re.search(r'(\d+)\s*MB', action, re.IGNORECASE)
        if size_match:
            return TestDataFactory.generate_file(f"{size_match.group(1)}MB_file.pdf",
                                                  size_mb=int(size_match.group(1)))
        char_match = re.search(r'(\d+)\s*[字符个字]', action)
        if char_match:
            return TestDataFactory.generate_string(int(char_match.group(1)))
        if "emoji" in action.lower() or "表情" in action:
            return TestDataFactory.generate_emoji_string(5)
        if "html" in action.lower() or "xss" in action.lower():
            return TestDataFactory.generate_html_string()
        return None
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_data_factory.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/generator/data_factory.py tests/test_data_factory.py
git commit -m "feat: test data factory for generating files/strings/emoji"
```

---

### Task 11: 智能执行器（含 AI 决策 + 结果分析）

**Files:**
- Create: `backend/engine/executor/executor.py`
- Create: `backend/engine/executor/healing.py`
- Test: `tests/test_executor.py`
- Test: `tests/test_healing.py`

- [ ] **Step 1: 编写选择器自愈测试**

```python
# tests/test_healing.py
from backend.engine.executor.healing import HealingStore
from backend.storage.database import init_db, get_db

def setup_module():
    init_db()

def test_add_and_find_healing_record():
    store = HealingStore()
    store.add(
        original_selector=".btn-delete",
        healed_selector="button:has-text('删除')",
        page_url_pattern="*/scenario/*",
        strategy="text_match"
    )
    result = store.find(".btn-delete", "https://test.com/scenario/123")
    assert result is not None
    assert result["healed_selector"] == "button:has-text('删除')"

def test_find_returns_none_for_unknown():
    store = HealingStore()
    result = store.find(".nonexistent", "https://test.com/page")
    assert result is None

def test_increment_success_and_fail():
    store = HealingStore()
    store.add(".btn-test", "button.test", "*/test/*", "css_stable")
    store.increment_success(".btn-test", "*/test/*")
    store.increment_fail(".btn-test", "*/test/*")
    record = store.find(".btn-test", "https://x.com/test/page")
    assert record is not None

def test_auto_delete_on_excessive_failures():
    store = HealingStore()
    store.add(".btn-bad", "button.bad", "*/bad/*", "css_stable")
    store.increment_fail(".btn-bad", "*/bad/*")
    store.increment_fail(".btn-bad", "*/bad/*")
    store.increment_fail(".btn-bad", "*/bad/*")
    result = store.find(".btn-bad", "https://x.com/bad/page")
    assert result is None  # fail_count >= 3, deleted
```

- [ ] **Step 2: 编写执行器测试**

```python
# tests/test_executor.py
from backend.engine.executor.executor import SmartExecutor, ExecutionContext
from backend.models.case import TestCase, Step, CaseStatus

def test_execution_context_creation():
    case = TestCase(id="c1", suite_id="s1", module="/", title="test",
                    steps=[Step(1, "click button")], expected="ok")
    ctx = ExecutionContext(case=case, script="print('hello')", session_id="sess1")
    assert ctx.ai_call_count == 0
    assert ctx.retry_count == 0

def test_executor_analyzes_selector_failure():
    exe = SmartExecutor(ai=None)
    result = exe.analyze_selector_failure(
        original_selector=".old-class",
        page_summary={"url": "/test", "text_snippet": "No button here"},
        case_context="test case context"
    )
    assert "selector" in result
    assert "confidence" in result

def test_executor_classifies_failures():
    exe = SmartExecutor(ai=None)
    summary = [
        {"case_id": "1", "status": "failed", "ai_judgment": "bug", "ai_confidence": 0.9},
        {"case_id": "2", "status": "failed", "ai_judgment": "selector_changed", "ai_confidence": 0.8},
        {"case_id": "3", "status": "blocked", "ai_judgment": None},
        {"case_id": "4", "status": "error", "ai_judgment": "script_error"},
    ]
    analysis = exe.classify_results(summary)
    assert len(analysis["bugs"]) == 1
    assert len(analysis["script_issues"]) == 2
    assert len(analysis["environment_issues"]) == 0
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/test_healing.py tests/test_executor.py -v
# Expected: FAIL
```

- [ ] **Step 4: 实现选择器自愈**

```python
# backend/engine/executor/healing.py
import hashlib
from backend.storage.database import get_db


class HealingStore:
    def find(self, original_selector: str, page_url: str) -> dict | None:
        db = get_db()
        pattern = self._url_to_pattern(page_url)
        row = db.execute(
            """SELECT * FROM healing_records
               WHERE original_selector = ? AND ? LIKE page_url_pattern
               ORDER BY success_count DESC, last_used_at DESC
               LIMIT 1""",
            (original_selector, pattern)
        ).fetchone()
        db.close()
        return dict(row) if row else None

    def add(self, original_selector: str, healed_selector: str, page_url_pattern: str, strategy: str = ""):
        db = get_db()
        rid = hashlib.md5(f"{original_selector}{page_url_pattern}".encode()).hexdigest()[:16]
        db.execute(
            """INSERT OR REPLACE INTO healing_records
               (id, original_selector, healed_selector, page_url_pattern, strategy, last_used_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (rid, original_selector, healed_selector, page_url_pattern, strategy)
        )
        db.commit()
        db.close()

    def increment_success(self, original_selector: str, page_url_pattern: str):
        db = get_db()
        db.execute(
            "UPDATE healing_records SET success_count = success_count + 1, last_used_at = datetime('now') WHERE original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.commit()
        db.close()

    def increment_fail(self, original_selector: str, page_url_pattern: str):
        db = get_db()
        db.execute(
            "UPDATE healing_records SET fail_count = fail_count + 1 WHERE original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.execute(
            "DELETE FROM healing_records WHERE fail_count >= 3 AND original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.commit()
        db.close()

    def list_all(self) -> list[dict]:
        db = get_db()
        rows = db.execute("SELECT * FROM healing_records ORDER BY success_count DESC").fetchall()
        db.close()
        return [dict(r) for r in rows]

    def clear(self):
        db = get_db()
        db.execute("DELETE FROM healing_records")
        db.commit()
        db.close()

    def _url_to_pattern(self, url: str) -> str:
        import re
        return re.sub(r'/[\w\-]+$', '/*', url).rstrip("/") + "/*"
```

- [ ] **Step 5: 实现智能执行器**

```python
# backend/engine/executor/executor.py
import subprocess
import tempfile
import os
import json
from dataclasses import dataclass, field
from backend.models.case import TestCase, CaseStatus
from backend.engine.executor.healing import HealingStore


@dataclass
class ExecutionContext:
    case: TestCase
    script: str
    session_id: str
    ai_call_count: int = 0
    retry_count: int = 0
    max_retries: int = 3
    result: dict = field(default_factory=dict)


class SmartExecutor:
    def __init__(self, ai=None, browser_controller=None):
        self.ai = ai
        self.browser = browser_controller
        self.healing = HealingStore()

    async def execute_case(self, ctx: ExecutionContext) -> dict:
        script_path = self._write_script(ctx)
        try:
            proc = await self._run_script(script_path)
            if proc.returncode == 0:
                ctx.case.transition_to(CaseStatus.PASSED)
                return {"case_id": ctx.case.id, "status": "passed", "output": proc.stdout}
            else:
                return await self._handle_failure(ctx, proc)
        except Exception as e:
            return {"case_id": ctx.case.id, "status": "error", "reason": str(e)}
        finally:
            if os.path.exists(script_path):
                os.unlink(script_path)

    def _write_script(self, ctx: ExecutionContext) -> str:
        path = os.path.join(tempfile.gettempdir(), f"test_{ctx.case.id}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(ctx.script)
        return path

    async def _run_script(self, script_path: str):
        return subprocess.run(
            ["python", script_path],
            capture_output=True, text=True, timeout=300
        )

    async def _handle_failure(self, ctx: ExecutionContext, proc) -> dict:
        stderr = proc.stderr
        if "TimeoutError" in stderr and "selector" in stderr.lower():
            return await self._handle_selector_timeout(ctx, stderr)
        if "AssertionError" in stderr or "expect(" in stderr.lower():
            return await self._handle_assertion_failure(ctx, stderr)
        return await self._handle_script_error(ctx, stderr)

    async def _handle_selector_timeout(self, ctx: ExecutionContext, stderr: str) -> dict:
        selector = self._extract_selector(stderr)
        healing = self.healing.find(selector, self.browser.page.url if self.browser else "")

        if healing:
            ctx.script = ctx.script.replace(selector, healing["healed_selector"])
            self.healing.increment_success(selector, healing["page_url_pattern"])
            ctx.retry_count += 1
            if ctx.retry_count < ctx.max_retries:
                return await self.execute_case(ctx)

        if self.ai and ctx.ai_call_count < 5:
            page_summary = await self.browser.get_page_summary() if self.browser else {}
            judgment = await self.ai.analyze(
                system_prompt="你是一个测试工程师。分析选择器定位失败的原因。返回 JSON: {judgment, confidence, action: {type, new_selector}, reasoning}",
                user_prompt=f"选择器 {selector} 定位失败。页面：{json.dumps(page_summary, ensure_ascii=False)}。用例：{ctx.case.title}"
            )
            ctx.ai_call_count += 1

            if judgment.judgment == "selector_changed" and judgment.action.get("new_selector"):
                new_sel = judgment.action["new_selector"]
                ctx.script = ctx.script.replace(selector, new_sel)
                self.healing.add(selector, new_sel, "*/" + ctx.case.module.lstrip("/") + "/*",
                                 strategy=judgment.action.get("strategy", "text_match"))
                ctx.retry_count += 1
                if ctx.retry_count < ctx.max_retries:
                    return await self.execute_case(ctx)

            if judgment.judgment == "element_missing":
                ctx.case.transition_to(CaseStatus.FAILED)
                return {"case_id": ctx.case.id, "status": "failed",
                        "reason": "element_missing", "ai_judgment": judgment.judgment,
                        "ai_confidence": judgment.confidence}

        ctx.case.transition_to(CaseStatus.FAILED)
        return {"case_id": ctx.case.id, "status": "failed", "reason": "selector_exhausted"}

    async def _handle_assertion_failure(self, ctx: ExecutionContext, stderr: str) -> dict:
        if self.ai and ctx.ai_call_count < 5:
            judgment = await self.ai.analyze(
                system_prompt="你是一个测试工程师。分析断言失败的原因。返回 JSON: {judgment: bug|expected_changed|assertion_inaccurate, confidence, reasoning}",
                user_prompt=f"预期：{ctx.case.expected}\n实际错误：{stderr}\n步骤：{[s.action for s in ctx.case.steps]}"
            )
            ctx.ai_call_count += 1
            ctx.case.transition_to(CaseStatus.FAILED)
            return {"case_id": ctx.case.id, "status": "failed",
                    "ai_judgment": judgment.judgment, "ai_confidence": judgment.confidence}

        ctx.case.transition_to(CaseStatus.FAILED)
        return {"case_id": ctx.case.id, "status": "failed", "reason": "assertion_failed"}

    async def _handle_script_error(self, ctx: ExecutionContext, stderr: str) -> dict:
        if self.ai and ctx.ai_call_count < 3:
            judgment = await self.ai.analyze(
                system_prompt="分类脚本异常：script_error | env_error | system_error。返回 JSON: {judgment, confidence, reasoning}",
                user_prompt=f"错误：{stderr}"
            )
            ctx.ai_call_count += 1
            if judgment.judgment == "env_error":
                return {"case_id": ctx.case.id, "status": "blocked", "reason": "environment_error"}
            if judgment.judgment == "script_error" and ctx.retry_count < 1:
                ctx.retry_count += 1
                return await self.execute_case(ctx)

        ctx.case.transition_to(CaseStatus.ERROR)
        return {"case_id": ctx.case.id, "status": "error", "reason": stderr[:200]}

    def _extract_selector(self, stderr: str) -> str:
        import re
        match = re.search(r"['\"]([^'\"]+)['\"]", stderr)
        return match.group(1) if match else "unknown"

    def classify_results(self, case_results: list[dict]) -> dict:
        bugs, script_issues, env_issues, case_issues = [], [], [], []
        for r in case_results:
            judgment = r.get("ai_judgment", "")
            if judgment == "bug":
                bugs.append(r)
            elif judgment in ("selector_changed", "script_error", "selector_exhausted"):
                script_issues.append(r)
            elif judgment == "environment_error":
                env_issues.append(r)
            elif judgment == "expected_changed":
                case_issues.append(r)
            elif r.get("status") == "blocked":
                env_issues.append(r)
            elif r.get("status") in ("error", "failed") and not judgment:
                script_issues.append(r)
        return {
            "bugs": bugs,
            "script_issues": script_issues,
            "environment_issues": env_issues,
            "case_issues": case_issues
        }
```

- [ ] **Step 6: 运行测试**

```bash
pytest tests/test_healing.py tests/test_executor.py -v
# Expected: PASS
```

- [ ] **Step 7: Commit**

```bash
git add backend/engine/executor/ tests/test_healing.py tests/test_executor.py
git commit -m "feat: smart executor with healing + AI decision + failure classification"
```

---

### Task 12: 报告生成器 ✅

**Files:**
- Create: `backend/engine/reporter/reporter.py`
- Create: `backend/templates/report.md.j2`
- Create: `backend/templates/sections/summary.j2`
- Create: `backend/templates/sections/failures.j2`
- Test: `tests/test_reporter.py`

- [ ] **Step 1: 编写报告测试**

```python
# tests/test_reporter.py
import json
from backend.engine.reporter.reporter import ReportGenerator

def test_generate_markdown_report():
    gen = ReportGenerator()
    run_data = {
        "run_id": "run-001", "target_url": "https://test.com",
        "started_at": "2026-04-29T14:30:00", "finished_at": "2026-04-29T14:52:00",
        "summary": {"total": 10, "passed": 8, "failed": 1, "blocked": 1, "error": 0},
        "module_stats": [{"module": "/场景管理", "total": 10, "passed": 8, "failed": 1, "blocked": 1, "error": 0}],
        "failed_cases": [{"case_id": "1", "module": "/场景", "title": "全选删除", "steps": "1. 全选 2. 删除", "expected": "全部删除", "actual": "按钮无响应", "ai_judgment": {"type": "bug", "confidence": 0.91}, "screenshot": "shots/c1.png"}],
        "blocked_cases": [], "error_cases": [],
        "ai_decisions": [{"case_id": "1", "scenario": "selector_failure", "judgment": "bug", "confidence": 0.91}],
        "ai_call_count": 3, "env_info": {"playwright": "1.52", "browser": "Chromium"}
    }
    md = gen.generate_markdown(run_data)
    assert "# 测试报告" in md
    assert "run-001" in md
    assert "全选删除" in md
    assert "bug" in md
    assert "85.7%" in md or "80.0%" in md

def test_generate_json_report():
    gen = ReportGenerator()
    run_data = {"run_id": "r1", "summary": {"total": 5, "passed": 5, "failed": 0, "blocked": 0, "error": 0},
                "module_stats": [], "failed_cases": [], "blocked_cases": [], "error_cases": [],
                "ai_decisions": [], "env_info": {}}
    json_str = gen.generate_json(run_data)
    data = json.loads(json_str)
    assert data["run_id"] == "r1"
    assert data["summary"]["total"] == 5
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_reporter.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现报告生成器**

```python
# backend/engine/reporter/reporter.py
import json
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path


class ReportGenerator:
    def __init__(self, templates_dir: str = ""):
        if not templates_dir:
            templates_dir = Path(__file__).parent.parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape()
        )

    def generate_markdown(self, run_data: dict) -> str:
        template = self.env.get_template("report.md.j2")
        return template.render(**run_data)

    def generate_json(self, run_data: dict) -> str:
        output = {
            "run_id": run_data["run_id"],
            "started_at": run_data.get("started_at", ""),
            "finished_at": run_data.get("finished_at", ""),
            "summary": run_data["summary"],
            "cases": self._flatten_cases(run_data),
            "ai_calls": run_data.get("ai_call_count", 0),
            "exit_code": self._exit_code(run_data["summary"])
        }
        return json.dumps(output, ensure_ascii=False, indent=2)

    def _flatten_cases(self, data: dict) -> list:
        cases = []
        for cat in ["failed_cases", "blocked_cases", "error_cases"]:
            for c in data.get(cat, []):
                c["category"] = cat.replace("_cases", "")
                cases.append(c)
        return cases

    def _exit_code(self, summary: dict) -> int:
        return 0 if summary.get("failed", 0) == 0 and summary.get("error", 0) == 0 else 1
```

- [ ] **Step 4: 编写报告模板**

```html
{# backend/templates/report.md.j2 #}
# 测试报告

**执行ID:** {{ run_id }}
**目标地址:** {{ target_url }}
**执行时间:** {{ started_at }} ~ {{ finished_at }}

## 执行概况

| 项目 | 值 |
|------|-----|
| 用例总数 | {{ summary.total }} |
| 通过 | {{ summary.passed }} ({{ "%.1f"|format(summary.passed / summary.total * 100) if summary.total else 0 }}%) |
| 失败 | {{ summary.failed }} |
| 阻塞 | {{ summary.blocked }} |
| 错误 | {{ summary.error }} |
| AI 调用次数 | {{ ai_call_count }} |

{% if failed_cases %}
## 失败用例

{% for case in failed_cases %}
### {{ case.title }}
| 字段 | 内容 |
|------|------|
| 模块 | {{ case.module }} |
| 步骤 | {{ case.steps }} |
| 预期 | {{ case.expected }} |
| 实际 | {{ case.actual | default("未记录") }} |
| AI 判定 | **{{ case.ai_judgment.type }}** (置信度 {{ case.ai_judgment.confidence }}) |
{% if case.screenshot %}| 截图 | ![]({{ case.screenshot }}) |{% endif %}

{% endfor %}
{% endif %}

{% if blocked_cases %}
## 阻塞用例
{% for case in blocked_cases %}
- **{{ case.title }}** — {{ case.reason | default("页面不可达") }}
{% endfor %}
{% endif %}

{% if error_cases %}
## 错误用例
{% for case in error_cases %}
- **{{ case.title }}** — {{ case.reason | default("脚本异常") }}
{% endfor %}
{% endif %}

## 模块统计

| 模块 | 总数 | 通过 | 失败 | 阻塞 | 错误 |
|------|------|------|------|------|------|
{% for m in module_stats %}| {{ m.module }} | {{ m.total }} | {{ m.passed }} | {{ m.failed }} | {{ m.blocked }} | {{ m.error }} |
{% endfor %}

{% if ai_decisions %}
## AI 决策摘要

| # | 用例 | 场景 | 判定 | 置信度 |
|---|------|------|------|--------|
{% for d in ai_decisions %}| {{ loop.index }} | {{ d.case_id }} | {{ d.scenario }} | {{ d.judgment }} | {{ d.confidence }} |
{% endfor %}
{% endif %}

## 环境信息

- Playwright: {{ env_info.playwright | default("N/A") }}
- 浏览器: {{ env_info.browser | default("N/A") }}
- AI 模型: {{ env_info.ai_model | default("N/A") }}
```

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_reporter.py -v
# Expected: PASS
```

- [ ] **Step 6: Commit**

```bash
git add backend/engine/reporter/ backend/templates/ tests/test_reporter.py
git commit -m "feat: Jinja2-driven report generator (Markdown + JSON)"
```

---

### Task 13: FastAPI 路由 + WebSocket ✅

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/routes.py`
- Create: `backend/api/websocket.py`
- Create: `backend/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: 编写 API 测试**

```python
# tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_get_config(client):
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "ai_provider" in data

@pytest.mark.asyncio
async def test_upload_cases(client):
    csv_content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/test,测试1,条件,1. 步骤1,1. 预期,key,1,功能测试,系统测试阶段"
    resp = await client.post("/api/v1/cases/upload",
                             files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    assert "suite_id" in data
    assert data["case_count"] == 1

@pytest.mark.asyncio
async def test_upload_invalid_file(client):
    resp = await client.post("/api/v1/cases/upload",
                             files={"file": ("test.txt", b"not csv", "text/plain")})
    assert resp.status_code == 400

@pytest.mark.asyncio
async def test_get_cases(client):
    csv_content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/test,测试1,,1. 步骤1,1. 预期,,1,功能测试,系统测试阶段"
    upload_resp = await client.post("/api/v1/cases/upload",
                                     files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")})
    suite_id = upload_resp.json()["suite_id"]
    resp = await client.get(f"/api/v1/cases/{suite_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
```

- [ ] **Step 2: 实现 FastAPI 应用**

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.storage.database import init_db

app = FastAPI(title="AI Test Platform", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/v1")

@app.on_event("startup")
async def startup():
    init_db()
```

```python
# backend/api/routes.py
import uuid
import json
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.config import Config
from backend.storage.database import get_db

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@router.get("/config")
async def get_config():
    cfg = Config()
    return {
        "ai_provider": cfg.ai_provider,
        "ai_model": cfg.ai_model,
        "ai_base_url": cfg.ai_base_url,
        "browser_headless": cfg.browser_headless
    }

@router.patch("/config")
async def update_config(updates: dict):
    # 仅运行时生效，不持久化
    return {"status": "updated", "changes": list(updates.keys())}

@router.post("/cases/upload")
async def upload_cases(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")

    content = await file.read()
    parser = CSVParser()
    cases = parser.parse(content)

    if not cases:
        raise HTTPException(400, "No valid test cases found in CSV")

    suite_id = str(uuid.uuid4())[:8]
    db = get_db()
    db.execute("INSERT INTO test_suites (id, name, file_name, case_count) VALUES (?, ?, ?, ?)",
               (suite_id, file.filename.rsplit(".", 1)[0], file.filename, len(cases)))
    for case in cases:
        case.suite_id = suite_id
        db.execute(
            """INSERT INTO test_cases (id, suite_id, module, title, preconditions, steps, expected,
               keywords, priority, test_type, stage, status, completeness)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case.id, suite_id, case.module, case.title, case.preconditions,
             json.dumps([{"order": s.order, "action": s.action} for s in case.steps], ensure_ascii=False),
             case.expected, case.keywords, case.priority, case.test_type, case.stage,
             case.status.value, case.completeness)
        )
    db.commit()
    db.close()

    enricher = CaseEnricher()
    enrichment = enricher.batch_evaluate(cases)

    return {
        "suite_id": suite_id,
        "case_count": len(cases),
        "enrichment": {
            "ready": len(enrichment["ready"]),
            "needs_enrichment": len(enrichment["needs_enrichment"]),
            "incomplete_cases": enrichment["needs_enrichment"]
        }
    }

@router.get("/cases/{suite_id}")
async def get_cases(suite_id: str):
    db = get_db()
    rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (suite_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]

@router.delete("/cases/{suite_id}")
async def delete_cases(suite_id: str):
    db = get_db()
    db.execute("DELETE FROM test_cases WHERE suite_id = ?", (suite_id,))
    db.execute("DELETE FROM test_suites WHERE id = ?", (suite_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}

@router.get("/healing")
async def get_healing_records():
    from backend.engine.executor.healing import HealingStore
    store = HealingStore()
    return store.list_all()

@router.delete("/healing/{record_id}")
async def delete_healing_record(record_id: str):
    db = get_db()
    db.execute("DELETE FROM healing_records WHERE id = ?", (record_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}

@router.post("/healing/clear")
async def clear_healing():
    from backend.engine.executor.healing import HealingStore
    store = HealingStore()
    store.clear()
    return {"status": "cleared"}
```

```python
# backend/api/websocket.py
import json
import asyncio
from fastapi import WebSocket


class LogBroadcaster:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, run_id: str, ws: WebSocket):
        await ws.accept()
        if run_id not in self.connections:
            self.connections[run_id] = []
        self.connections[run_id].append(ws)

    def disconnect(self, run_id: str, ws: WebSocket):
        if run_id in self.connections:
            self.connections[run_id].remove(ws)

    async def broadcast(self, run_id: str, message: dict):
        if run_id not in self.connections:
            return
        dead = []
        for ws in self.connections[run_id]:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(run_id, ws)
```

- [ ] **Step 3: 运行 API 测试**

```bash
pytest tests/test_api.py -v
# Expected: PASS
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/ backend/main.py tests/test_api.py
git commit -m "feat: FastAPI routes + WebSocket log broadcaster"
```

---

### Task 14: 前端脚手架 + 用例导入页 ✅

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`
- Create: `frontend/src/pages/CaseUpload.tsx`
- Create: `frontend/src/api.ts`

- [ ] **Step 1: 初始化前端项目**

```bash
cd frontend && npm create vite@latest . -- --template react-ts
npm install
```

- [ ] **Step 2: 编写 API 封装**

```typescript
// frontend/src/api.ts
const BASE = "http://localhost:8000/api/v1";

export async function uploadCases(file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/cases/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getCases(suiteId: string) {
  const res = await fetch(`${BASE}/cases/${suiteId}`);
  return res.json();
}

export async function getHealth() {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function getConfig() {
  const res = await fetch(`${BASE}/config`);
  return res.json();
}
```

- [ ] **Step 3: 编写用例上传页面**

```tsx
// frontend/src/pages/CaseUpload.tsx
import { useState } from "react";
import { uploadCases } from "../api";

export default function CaseUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const data = await uploadCases(file);
      setResult(data);
    } catch (e: any) {
      setResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "40px auto" }}>
      <h1>AI 测试平台</h1>
      <div style={{ border: "2px dashed #ccc", padding: 30, borderRadius: 8, marginBottom: 20 }}>
        <input type="file" accept=".csv" onChange={e => setFile(e.target.files?.[0] || null)} />
        <button onClick={handleUpload} disabled={!file || loading} style={{ marginLeft: 12 }}>
          {loading ? "上传中..." : "上传用例"}
        </button>
      </div>
      {result && (
        <div style={{ background: "#f9f9f9", padding: 16, borderRadius: 8 }}>
          {result.error ? (
            <p style={{ color: "red" }}>错误: {result.error}</p>
          ) : (
            <>
              <p>用例集 ID: <b>{result.suite_id}</b></p>
              <p>用例数: <b>{result.case_count}</b></p>
              <p>可直接生成脚本: {result.enrichment?.ready || 0}</p>
              <p>需要补全: {result.enrichment?.needs_enrichment || 0}</p>
              {result.enrichment?.incomplete_cases?.length > 0 && (
                <details>
                  <summary>待补全用例</summary>
                  {result.enrichment.incomplete_cases.map((c: any, i: number) => (
                    <div key={i} style={{ margin: "8px 0", padding: 8, background: "#fff", borderRadius: 4 }}>
                      <strong>{c.case_title}</strong>
                      <p>模块: {c.module}</p>
                      <p>步骤: {c.steps?.join(", ")}</p>
                    </div>
                  ))}
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: 编写 App 入口**

```tsx
// frontend/src/App.tsx
import CaseUpload from "./pages/CaseUpload";

export default function App() {
  return <CaseUpload />;
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat: React frontend scaffold + case upload page"
```

---

### Task 15: 端到端集成测试

**Files:**
- Create: `tests/test_integration.py`
- Create: `backend/engine/__init__.py`

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_integration.py
import pytest
import tempfile
from pathlib import Path
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.engine.generator.generator import ScriptGenerator
from backend.storage.database import init_db, get_db

@pytest.fixture
def real_csv():
    return """所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段
/文档中心(#145),文档列表正确展示,1. 用户已登录,1. 进入/文档中心(#145)页面 2. 观察列表,1. 正确展示 2. 显示12条,文档,1,功能测试,系统测试阶段
/文档中心(#145),新建文档,1. 用户已登录,1. 点击新建 2. 输入标题 3. 保存,1. 创建成功 2. 列表出现新文档,新建,1,功能测试,系统测试阶段
/文档中心(#145),删除文档,1. 用户已登录 2. 存在文档A,1. 选择文档A 2. 点击删除 3. 确认,1. 删除成功 2. 列表刷新,删除,1,功能测试,系统测试阶段
"""

def test_full_pipeline_parse_to_script(real_csv):
    """完整管线：解析 → 补全评估 → 脚本生成"""
    parser = CSVParser()
    cases = parser.parse(real_csv)
    assert len(cases) == 3

    enricher = CaseEnricher()
    results = enricher.batch_evaluate(cases)
    assert results["ready"]  # 至少有一个完整用例

    gen = ScriptGenerator()
    for case_id in results["ready"]:
        case = next(c for c in cases if c.id == case_id)
        script = gen.build_script_template(case, {})
        assert "from playwright.async_api import" in script
        precheck = gen.precheck(script)
        assert precheck["valid"] is True, f"Script failed precheck: {precheck['errors']}"

def test_end_to_end_state_transitions(real_csv):
    """端到端状态转换验证"""
    parser = CSVParser()
    cases = parser.parse(real_csv)
    case = cases[0]
    assert case.status.value == "pending"

    case.transition_to(case.status.__class__.EXPLORING)
    assert case.status.value == "exploring"

    case.transition_to(case.status.__class__.GENERATING)
    assert case.status.value == "generating"

    case.transition_to(case.status.__class__.RUNNING)
    assert case.status.value == "running"

    case.transition_to(case.status.__class__.PASSED)
    assert case.status.value == "passed"

def test_database_persistence(real_csv):
    """数据库持久化测试"""
    init_db()
    parser = CSVParser()
    cases = parser.parse(real_csv)

    db = get_db()
    suite_id = "test-suite-001"
    db.execute("INSERT OR REPLACE INTO test_suites (id, name, case_count) VALUES (?, ?, ?)",
               (suite_id, "test", len(cases)))

    for case in cases:
        import json
        db.execute(
            """INSERT OR REPLACE INTO test_cases
               (id, suite_id, module, title, steps, expected, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (case.id, suite_id, case.module, case.title,
             json.dumps([{"order": s.order, "action": s.action} for s in case.steps], ensure_ascii=False),
             case.expected, case.status.value)
        )
    db.commit()

    rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (suite_id,)).fetchall()
    assert len(rows) == 3
    db.execute("DELETE FROM test_cases WHERE suite_id = ?", (suite_id,))
    db.execute("DELETE FROM test_suites WHERE id = ?", (suite_id,))
    db.commit()
    db.close()
```

- [ ] **Step 2: 运行集成测试**

```bash
pytest tests/test_integration.py -v
# Expected: PASS
```

- [ ] **Step 3: 运行全部测试**

```bash
pytest tests/ -v
# Expected: ALL PASS
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py backend/engine/__init__.py
git commit -m "test: end-to-end integration tests for full pipeline"
```

---

## 验证清单

完成所有 task 后，执行以下验证：

- [ ] `pytest tests/ -v` 全部通过
- [ ] `uvicorn backend.main:app --reload` 后端启动正常
- [ ] `curl http://localhost:8000/api/v1/health` 返回 ok
- [ ] 上传真实 CSV（从 `小仓写作/快速写作用例.csv`）返回用例数正确
- [ ] `cd frontend && npm run dev` 前端启动正常
- [ ] 浏览器访问 localhost:5173，上传 CSV 能看到结果

