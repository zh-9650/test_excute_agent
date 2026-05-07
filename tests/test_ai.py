import pytest
from backend.ai.base import AIResponse
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
    assert config.ai_model == "mimo-v2.5-pro"
    assert config.ai_base_url == "https://api.xiaomimimo.com/v1"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "qwen")
    monkeypatch.setenv("AI_MODEL", "qwen3.5-122b")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("AI_API_KEY", "sk-local")
    monkeypatch.setenv("AI_BACKUP_MODEL", "gpt-5.5")
    monkeypatch.setenv("BROWSER_HEADLESS", "true")

    config = Config()
    assert config.ai_provider == "qwen"
    assert config.ai_model == "qwen3.5-122b"
    assert config.ai_base_url == "http://localhost:8080/v1"
    assert config.ai_api_key == "sk-local"
    assert config.ai_backup_model == "gpt-5.5"
    assert config.browser_headless is True


def test_config_from_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"ai_provider": "deepseek", "ai_model": "deepseek-chat", "ai_base_url": "https://custom.api.com/v1"}')
    config = Config(config_path=str(config_file))
    assert config.ai_provider == "deepseek"
    assert config.ai_model == "deepseek-chat"
    assert config.ai_base_url == "https://custom.api.com/v1"


def test_config_create_provider():
    config = Config()
    config.ai_api_key = "sk-test"
    provider = config.create_provider()
    assert provider is not None
    assert provider.base_url == "https://api.xiaomimimo.com/v1"


def test_config_create_backup_provider_without_config():
    config = Config()
    config.ai_backup_model = ""
    provider = config.create_backup_provider()
    assert provider is None


def test_config_create_backup_provider():
    config = Config()
    config.ai_backup_model = "gpt-5.5"
    config.ai_backup_base_url = "https://relay.api.com/v1"
    config.ai_backup_api_key = "sk-backup"
    provider = config.create_backup_provider()
    assert provider is not None
