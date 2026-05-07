"""RunRecorder — 将 ExplorerAgent 的探索结果录制为 ActionIR

职责：
- 接收 ExplorerAgent 的 CaseExplorationResult
- 转换为 ActionIR 格式
- 管理截图目录
- 持久化 IR 到文件系统
"""

import os
import json
from datetime import datetime

from backend.engine.recorder.action_ir import ActionIR, ActionStep
from backend.engine.agent.explorer_agent import CaseExplorationResult


class RunRecorder:
    def __init__(self, run_id: str, output_dir: str = "test_artifacts"):
        self.run_id = run_id
        self.output_dir = output_dir
        self.artifact_dir = os.path.join(output_dir, run_id)
        self.screenshot_dir = os.path.join(self.artifact_dir, "screenshots")
        self.ir_dir = os.path.join(self.artifact_dir, "irs")
        self._tool_calls_log = []

        os.makedirs(self.screenshot_dir, exist_ok=True)
        os.makedirs(self.ir_dir, exist_ok=True)

    def record_case(self, case, exploration_result: CaseExplorationResult) -> ActionIR:
        """将用例探索结果录制为 ActionIR"""
        ir = ActionIR(
            run_id=self.run_id,
            case_id=exploration_result.case_id,
            case_title=exploration_result.case_title,
            module=getattr(case, "module", ""),
            expected=getattr(case, "expected", ""),
            status=exploration_result.status,
            start_time=datetime.now().isoformat(),
            total_ai_calls=exploration_result.total_ai_calls,
        )

        for step_result in exploration_result.steps:
            action_step = self._convert_step(step_result)
            ir.steps.append(action_step)

        ir.end_time = datetime.now().isoformat()
        return ir

    def _convert_step(self, step_result) -> ActionStep:
        """将 StepResult 转换为 ActionStep"""
        # 从 tool calls 中提取实际执行的动作
        action, locator, value = self._extract_action_from_tool_calls(step_result.actions)

        return ActionStep(
            order=step_result.step_num,
            natural_step=step_result.natural_step,
            action=action,
            locator=locator,
            value=value,
            target_ref=self._extract_ref(step_result.actions),
            reason=self._extract_reason(step_result.actions),
            confidence=self._extract_confidence(step_result.actions),
            before_url=step_result.url_before,
            after_url=step_result.url_after,
            screenshot_before=step_result.screenshot_before,
            screenshot_after=step_result.screenshot_after,
            status="passed" if step_result.success else "failed",
            error="" if step_result.success else step_result.message,
            tool_calls=step_result.actions,
        )

    def _extract_action_from_tool_calls(self, tool_calls: list) -> tuple:
        """从 tool calls 中提取动作类型、locator、value"""
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")

            # 跳过 snapshot 和 screenshot
            if name in ("snapshot", "screenshot", "wait"):
                continue

            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            # 从 result 中获取成功状态
            result = tc.get("result", {})
            if result and not result.get("success", True):
                continue

            return name, args.get("locator", {}), args.get("value", args.get("url", args.get("text", "")))

        return "unknown", {}, ""

    def _extract_ref(self, tool_calls: list) -> str:
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            if name in ("snapshot", "screenshot", "wait"):
                continue
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}
            return args.get("ref", "")
        return ""

    def _extract_reason(self, tool_calls: list) -> str:
        for tc in tool_calls:
            reason = tc.get("reason", "")
            if reason:
                return reason
        return ""

    def _extract_confidence(self, tool_calls: list) -> float:
        for tc in tool_calls:
            conf = tc.get("confidence", 0)
            if conf:
                return float(conf)
        return 0.0

    def save_ir(self, ir: ActionIR) -> str:
        """保存 ActionIR 到文件，返回文件路径"""
        filename = f"{ir.case_id}.json"
        path = os.path.join(self.ir_dir, filename)
        ir.save(path)
        return path

    def save_all_irs(self, irs: list[ActionIR]) -> str:
        """保存所有 IR 到合并文件"""
        path = os.path.join(self.artifact_dir, "action_ir.json")
        data = {
            "run_id": self.run_id,
            "generated_at": datetime.now().isoformat(),
            "case_count": len(irs),
            "cases": [ir.to_dict() for ir in irs],
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path

    def log_tool_call(self, tool_call: dict):
        """记录 tool call 到日志文件"""
        self._tool_calls_log.append(tool_call)

    def save_tool_calls_log(self) -> str:
        """保存 tool calls 日志"""
        path = os.path.join(self.artifact_dir, "tool_calls.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for tc in self._tool_calls_log:
                f.write(json.dumps(tc, ensure_ascii=False) + "\n")
        return path

    def get_screenshot_path(self, case_id: str, step_num: int, phase: str) -> str:
        """生成截图文件路径"""
        return os.path.join(self.screenshot_dir, f"{case_id}_step{step_num}_{phase}.png")
