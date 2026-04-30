"""AI 成本控制：去重/限制/批处理/降级/门禁/熔断"""

import time


class AIGuard:
    def __init__(self, max_per_case: int = 5, global_max_ratio: float = 2.0,
                 confidence_threshold: float = 0.5, melt_after: int = 3):
        self.max_per_case = max_per_case
        self.global_max_ratio = global_max_ratio
        self.confidence_threshold = confidence_threshold
        self.melt_after = melt_after  # 连续失败 N 条触发熔断

        self.case_call_counts: dict[str, int] = {}
        self.total_calls = 0
        self.total_steps = 0
        self.selector_cache: dict[str, str] = {}  # 同类型去重
        self.consecutive_fails = 0
        self.is_melted = False
        self.melt_reason = ""

    def can_call(self, case_id: str) -> bool:
        """检查是否允许对此用例做 AI 调用"""
        if self.is_melted:
            return False
        count = self.case_call_counts.get(case_id, 0)
        if count >= self.max_per_case:
            return False
        if self.total_steps > 0 and self.total_calls > self.total_steps * self.global_max_ratio:
            self.is_melted = True
            self.melt_reason = f"Global meltdown: {self.total_calls} AI calls for {self.total_steps} steps"
            return False
        return True

    def record_call(self, case_id: str):
        self.case_call_counts[case_id] = self.case_call_counts.get(case_id, 0) + 1
        self.total_calls += 1

    def record_step(self):
        self.total_steps += 1

    def check_confidence(self, confidence: float) -> bool:
        """置信度低于阈值返回 False，应标记人工确认"""
        return confidence >= self.confidence_threshold

    def record_fail(self):
        self.consecutive_fails += 1

    def record_pass(self):
        self.consecutive_fails = 0

    def should_melt(self, total_cases: int) -> bool:
        threshold = min(self.melt_after, int(total_cases * 0.2))
        if self.consecutive_fails >= threshold:
            self.is_melted = True
            self.melt_reason = f"Consecutive failures ({self.consecutive_fails}) reached threshold ({threshold})"
            return True
        return False

    def cache_selector(self, original: str, healed: str):
        self.selector_cache[original] = healed

    def get_cached(self, selector: str) -> str | None:
        return self.selector_cache.get(selector)

    def status(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_steps": self.total_steps,
            "case_counts": self.case_call_counts,
            "consecutive_fails": self.consecutive_fails,
            "melted": self.is_melted,
            "melt_reason": self.melt_reason,
        }
