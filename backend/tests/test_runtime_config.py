"""Covers the Settings screen's backing store: values save encrypted where
sensitive, round-trip through a fresh load (simulating a process restart),
and re-saving without retyping a secret doesn't blank it out."""
from backend.app import runtime_config
from backend.app.models import AppSetting


def test_save_persists_and_updates_in_memory_immediately(db):
    runtime_config.save(db, GEMINI_API_KEY="AIza-test123", GOOGLE_CLIENT_ID="client-abc")
    assert runtime_config.GEMINI_API_KEY == "AIza-test123"
    assert runtime_config.GOOGLE_CLIENT_ID == "client-abc"


def test_secret_values_are_encrypted_at_rest(db):
    runtime_config.save(db, GEMINI_API_KEY="AIza-supersecret")
    row = db.query(AppSetting).filter(AppSetting.key == "GEMINI_API_KEY").first()
    assert row.is_secret is True
    assert row.value != "AIza-supersecret"  # stored encrypted, not plaintext


def test_non_secret_values_are_stored_plainly(db):
    runtime_config.save(db, GOOGLE_CLIENT_ID="my-id.apps.googleusercontent.com")
    row = db.query(AppSetting).filter(AppSetting.key == "GOOGLE_CLIENT_ID").first()
    assert row.is_secret is False
    assert row.value == "my-id.apps.googleusercontent.com"


def test_load_from_db_restores_values_simulating_a_restart(db):
    runtime_config.save(db, GEMINI_API_KEY="AIza-restart-test", GOOGLE_CLIENT_SECRET="GOCSPX-restart")

    # Simulate a fresh process: reset the in-memory globals, then reload.
    runtime_config.GEMINI_API_KEY = ""
    runtime_config.GOOGLE_CLIENT_SECRET = ""
    runtime_config.load_from_db(db)

    assert runtime_config.GEMINI_API_KEY == "AIza-restart-test"
    assert runtime_config.GOOGLE_CLIENT_SECRET == "GOCSPX-restart"


def test_empty_values_do_not_overwrite_existing_settings(db):
    runtime_config.save(db, GEMINI_API_KEY="AIza-keep-me")
    runtime_config.save(db, GEMINI_API_KEY=None, GOOGLE_CLIENT_ID="new-client-id")
    assert runtime_config.GEMINI_API_KEY == "AIza-keep-me"
    assert runtime_config.GOOGLE_CLIENT_ID == "new-client-id"


def test_status_never_exposes_secret_values(db):
    runtime_config.save(db, GEMINI_API_KEY="AIza-should-not-leak", GOOGLE_CLIENT_SECRET="GOCSPX-should-not-leak")
    result = runtime_config.status(db)
    dumped = str(result)
    assert "AIza-should-not-leak" not in dumped
    assert "GOCSPX-should-not-leak" not in dumped
    assert result["gemini_api_key_set"] is True
    assert result["google_client_secret_set"] is True
