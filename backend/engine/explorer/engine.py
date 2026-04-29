import uuid
from dataclasses import dataclass, field
from backend.models.case import TestCase


@dataclass
class ExplorationResult:
    exploration_id: str
    pages_explored: list = field(default_factory=list)
    pages_skipped: list = field(default_factory=list)
    total_elements: int = 0
    coverage_score: float = 0.0


class ExplorationEngine:
    def __init__(self, browser=None, ai=None):
        self.browser = browser
        self.ai = ai

    def build_plan(self, cases: list[TestCase]) -> dict:
        pages = {}
        for case in cases:
            module = case.module
            if module not in pages:
                pages[module] = {
                    "module": module,
                    "url_hint": module,
                    "cases": [],
                    "steps_texts": set()
                }
            pages[module]["cases"].append(case.id)
            for step in case.steps:
                pages[module]["steps_texts"].add(step.action)
        return {"pages": list(pages.values()), "total_pages": len(pages), "total_cases": len(cases)}

    def _group_by_page(self, cases: list[TestCase]) -> dict:
        groups = {}
        for case in cases:
            key = case.module
            if key not in groups:
                groups[key] = []
            groups[key].append(case)
        return groups

    async def explore(self, cases: list[TestCase], session, target_url: str) -> ExplorationResult:
        exp_id = str(uuid.uuid4())[:8]
        plan = self.build_plan(cases)
        result = ExplorationResult(exploration_id=exp_id)

        for page_info in plan["pages"]:
            page_url = self._resolve_url(target_url, page_info["url_hint"])
            nav_result = await self.browser.goto(page_url)
            if not nav_result["success"]:
                result.pages_skipped.append({
                    "url": page_url, "reason": nav_result.get("error", "unknown"),
                    "module": page_info["module"]
                })
                continue

            await self.browser.dismiss_dialogs()
            await self.browser.wait_for_page_ready(strategy="networkidle")
            elements = await self.browser.collect_interactive_elements()
            result.pages_explored.append({
                "url": self.browser.page.url, "module": page_info["module"],
                "elements_found": len(elements),
                "elements": [{"tag": e.tag, "selector": e.selector, "text": e.text} for e in elements]
            })
            result.total_elements += len(elements)

        explored = len(result.pages_explored)
        total = len(plan["pages"]) or 1
        result.coverage_score = explored / total
        return result

    def _resolve_url(self, base_url: str, hint: str) -> str:
        if hint.startswith("http"):
            return hint
        return base_url.rstrip("/") + "/" + hint.lstrip("/")

    def generate_exploration_report(self, result: ExplorationResult) -> str:
        lines = [
            "# 探索报告", f"\n## 概况",
            f"- 已探索页面数：{len(result.pages_explored)}",
            f"- 跳过页面数：{len(result.pages_skipped)}",
            f"- 收集元素总数：{result.total_elements}",
            f"- 覆盖率：{result.coverage_score:.0%}",
        ]
        if result.pages_explored:
            lines.append("\n## 已探索页面")
            for p in result.pages_explored:
                lines.append(f"- {p['module']} → {p['url']} ({p['elements_found']} 个元素)")
        if result.pages_skipped:
            lines.append("\n## 跳过页面")
            for p in result.pages_skipped:
                lines.append(f"- {p['module']} → {p['url']} ({p['reason']})")
        return "\n".join(lines)
