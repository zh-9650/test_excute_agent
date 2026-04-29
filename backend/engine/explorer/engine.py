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
    def __init__(self, browser=None, ai=None, log_callback=None):
        self.browser = browser
        self.ai = ai
        self._log = log_callback or (lambda msg: None)

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

        await self._log(f"Exploration plan: {plan['total_pages']} pages, {plan['total_cases']} cases")
        page_descs = [f"{p['module']} ({len(p['cases'])} cases)" for p in plan["pages"]]
        await self._log(f"  Target pages: {', '.join(page_descs[:8])}{'...' if len(page_descs) > 8 else ''}")

        for i, page_info in enumerate(plan["pages"]):
            page_url = self._resolve_url(target_url, page_info["url_hint"])
            await self._log(f"  [{i+1}/{plan['total_pages']}] Navigating to: {page_url}")

            nav_result = await self.browser.goto(page_url)
            if not nav_result["success"]:
                reason = nav_result.get("error", "unknown")
                await self._log(f"    SKIPPED: {reason}")
                result.pages_skipped.append({
                    "url": page_url, "reason": reason,
                    "module": page_info["module"]
                })
                continue

            await self.browser.dismiss_dialogs()
            ready = await self.browser.wait_for_page_ready(strategy="networkidle")
            if not ready:
                await self._log(f"    Page not fully loaded, fallback wait...")
                await self.browser.wait_for_page_ready(strategy="domcontentloaded")

            await self._log(f"    Collecting interactive elements...")
            elements = await self.browser.collect_interactive_elements()

            tag_counts = {}
            for e in elements:
                tag_counts[e.tag] = tag_counts.get(e.tag, 0) + 1
            tag_summary = " ".join([f"{tag}:{cnt}" for tag, cnt in sorted(tag_counts.items())])

            await self._log(f"    Collected {len(elements)} elements [{tag_summary}]")

            result.pages_explored.append({
                "url": self.browser.page.url, "module": page_info["module"],
                "elements_found": len(elements),
                "elements": [{"tag": e.tag, "selector": e.selector, "text": e.text} for e in elements]
            })
            result.total_elements += len(elements)

        explored = len(result.pages_explored)
        total = len(plan["pages"]) or 1
        result.coverage_score = explored / total

        if result.pages_skipped:
            await self._log(f"WARNING: {len(result.pages_skipped)} pages skipped")
        await self._log(f"Exploration done: {explored}/{total} pages, {result.total_elements} elements, coverage {result.coverage_score:.0%}")

        return result

    def _resolve_url(self, base_url: str, hint: str) -> str:
        if hint.startswith("http"):
            return hint
        return base_url.rstrip("/") + "/" + hint.lstrip("/")

    def generate_exploration_report(self, result: ExplorationResult) -> str:
        lines = [
            "# Exploration Report", f"\n## Summary",
            f"- Pages explored: {len(result.pages_explored)}",
            f"- Pages skipped: {len(result.pages_skipped)}",
            f"- Total elements: {result.total_elements}",
            f"- Coverage: {result.coverage_score:.0%}",
        ]
        if result.pages_explored:
            lines.append("\n## Explored Pages")
            for p in result.pages_explored:
                lines.append(f"- {p['module']} -> {p['url']} ({p['elements_found']} elements)")
        if result.pages_skipped:
            lines.append("\n## Skipped Pages")
            for p in result.pages_skipped:
                lines.append(f"- {p['module']} -> {p['url']} ({p['reason']})")
        return "\n".join(lines)
