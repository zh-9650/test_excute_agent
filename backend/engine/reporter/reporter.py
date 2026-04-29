import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape


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
