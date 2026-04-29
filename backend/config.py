import os
import json
from pathlib import Path


class Config:
    def __init__(self, config_path: str = ""):
        self.ai_provider: str = "openai_compatible"
        self.ai_model: str = "Qwen3.5-122B"
        self.ai_base_url: str = "https://qwen.cangjieit.cn:8443/v1"
        self.ai_api_key: str = "sk-Q7m9X2pL4vR8nK1jW5tY3bH6cF0dG9sA"
        self.ai_backup_model: str = ""
        self.ai_backup_base_url: str = ""
        self.ai_backup_api_key: str = ""
        self.browser_headless: bool = False

        if config_path and Path(config_path).exists():
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(self, k):
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
