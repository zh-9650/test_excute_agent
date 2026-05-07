"""Action IR — 脚本生成的唯一中间表示

每个测试步骤记录为一个 ActionStep，包含：
- 自然语言步骤描述
- 实际执行的动作类型和参数
- 定位策略（locator）
- 执行前后的 URL 和截图路径
- 执行状态

ActionIR 是一个用例的完整录制结果。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActionStep:
    order: int
    natural_step: str              # 原始步骤描述
    action: str                    # click / fill / navigate / hover / select_option / assert_visible / ...
    locator: dict = field(default_factory=dict)   # {"strategy": "placeholder", "value": "..."}
    value: str = ""                # fill 的输入值、navigate 的 URL 等
    target_ref: str = ""           # snapshot 中的 ref
    reason: str = ""               # AI 决策理由
    confidence: float = 0.0        # AI 置信度
    before_url: str = ""
    after_url: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""
    status: str = "passed"         # passed / failed / blocked / skipped
    error: str = ""
    tool_calls: list = field(default_factory=list)  # 原始 tool call 记录

    def to_dict(self) -> dict:
        d = {
            "order": self.order,
            "natural_step": self.natural_step,
            "action": self.action,
            "locator": self.locator,
            "value": self.value,
            "target_ref": self.target_ref,
            "reason": self.reason,
            "confidence": self.confidence,
            "before_url": self.before_url,
            "after_url": self.after_url,
            "status": self.status,
        }
        if self.screenshot_before:
            d["screenshot_before"] = self.screenshot_before
        if self.screenshot_after:
            d["screenshot_after"] = self.screenshot_after
        if self.error:
            d["error"] = self.error
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ActionStep":
        return cls(
            order=data.get("order", 0),
            natural_step=data.get("natural_step", ""),
            action=data.get("action", ""),
            locator=data.get("locator", {}),
            value=data.get("value", ""),
            target_ref=data.get("target_ref", ""),
            reason=data.get("reason", ""),
            confidence=data.get("confidence", 0.0),
            before_url=data.get("before_url", ""),
            after_url=data.get("after_url", ""),
            screenshot_before=data.get("screenshot_before", ""),
            screenshot_after=data.get("screenshot_after", ""),
            status=data.get("status", "passed"),
            error=data.get("error", ""),
            tool_calls=data.get("tool_calls", []),
        )


@dataclass
class ActionIR:
    run_id: str
    case_id: str
    case_title: str
    module: str = ""
    expected: str = ""
    steps: list[ActionStep] = field(default_factory=list)
    status: str = "pending"        # pending / passed / failed / blocked / error
    start_time: str = ""
    end_time: str = ""
    total_ai_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_title": self.case_title,
            "module": self.module,
            "expected": self.expected,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_ai_calls": self.total_ai_calls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionIR":
        return cls(
            run_id=data.get("run_id", ""),
            case_id=data.get("case_id", ""),
            case_title=data.get("case_title", ""),
            module=data.get("module", ""),
            expected=data.get("expected", ""),
            steps=[ActionStep.from_dict(s) for s in data.get("steps", [])],
            status=data.get("status", "pending"),
            start_time=data.get("start_time", ""),
            end_time=data.get("end_time", ""),
            total_ai_calls=data.get("total_ai_calls", 0),
        )

    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "ActionIR":
        return cls.from_dict(json.loads(json_str))

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> "ActionIR":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())
