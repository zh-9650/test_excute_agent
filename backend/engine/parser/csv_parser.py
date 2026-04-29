import csv
import io
import re
import uuid
from backend.models.case import TestCase, Step


class CSVParser:
    REQUIRED_COLUMNS = ["所属模块", "测试点", "步骤", "预期"]
    # 列名别名（不同禅道版本的列名差异）
    COLUMN_ALIASES = {
        "测试点": ["测试点", "用例标题", "测试标题"],
        "用例类型": ["用例类型", "测试类型"],
    }

    def parse(self, content) -> list[TestCase]:
        if isinstance(content, bytes):
            content = self._detect_and_decode(content)

        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            return []

        fieldnames = self._normalize_fieldnames(reader.fieldnames)
        reader.fieldnames = fieldnames

        missing = [c for c in self.REQUIRED_COLUMNS if c not in fieldnames]
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
        nav_indicators = ["进入", "打开", "页面", "URL", "登录", "跳转"]
        specific_indicators = ["点击", "输入", "选择", "上传", "删除"]
        combined = title + steps
        has_nav = any(ind in combined for ind in nav_indicators)
        has_specific = any(ind in combined for ind in specific_indicators)
        if has_nav and has_specific:
            return "complete"
        if has_specific:
            return "incomplete"
        return "unknown"

    def _normalize_fieldnames(self, fieldnames: list[str]) -> list[str]:
        result = []
        for name in fieldnames:
            normalized = name.strip()
            for canonical, aliases in self.COLUMN_ALIASES.items():
                if normalized in aliases:
                    normalized = canonical
                    break
            result.append(normalized)
        return result

    def _detect_and_decode(self, data: bytes) -> str:
        for encoding in ["utf-8", "gbk", "gb2312", "gb18030"]:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return data.decode("utf-8", errors="replace")
