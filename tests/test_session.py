import json
from pathlib import Path
from backend.engine.explorer.session import SessionManager, SessionState


def test_session_created_with_credentials():
    sm = SessionManager()
    state = sm.create(target_url="https://test.example.com",
                      username="admin", password="test123")
    assert state.target_url == "https://test.example.com"
    assert state.username == "admin"
    assert state.password != "test123"
    assert state.storage_state is None


def test_save_and_load_storage_state(tmp_path):
    sm = SessionManager(storage_dir=str(tmp_path))
    state = sm.create("https://test.example.com", "admin", "pass")
    fake_state = {"cookies": [{"name": "token", "value": "abc"}]}
    sm.save_storage_state(state.id, fake_state)
    loaded = sm.load_storage_state(state.id)
    assert loaded == fake_state


def test_session_expiry_detection():
    sm = SessionManager()
    state = sm.create("https://test.example.com", "admin", "pass")
    assert sm.is_expired(state) is False


def test_credential_encryption():
    sm = SessionManager()
    state = sm.create("https://test.example.com", "admin", "s3cret!")
    assert state.password != "s3cret!"
    decrypted = sm.get_credentials(state.id)
    assert decrypted["username"] == "admin"
    assert decrypted["password"] == "s3cret!"
