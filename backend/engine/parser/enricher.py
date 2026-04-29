class CaseEnricher:
    def __init__(self, ai_provider=None):
        self.ai = ai_provider

    def evaluate(self, case) -> dict:
        if case.completeness == "complete":
            return {"needs_enrichment": False, "case_id": case.id}

        template = {
            "target_url": case.module,
            "target_url_hint": "建议的目标页面路径",
            "selector_hint": "",
            "selector_hint_desc": "可选，描述目标元素（如：列表页的编辑按钮、弹窗中的保存按钮）",
            "extra_note": "",
            "extra_note_desc": "补充说明（如：需要先选择某条数据）"
        }

        return {
            "needs_enrichment": True,
            "case_id": case.id,
            "case_title": case.title,
            "module": case.module,
            "steps": [s.action for s in case.steps],
            "template": template
        }

    def batch_evaluate(self, cases: list) -> dict:
        needs, ready = [], []
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
