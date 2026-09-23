"""Covers the /api/settings endpoints (previously untested), including the
new ai_model field added after a real Gemini model retirement broke
extraction for a user with no way to fix it short of a new download."""
from backend.app import runtime_config
from backend.app.api.routers.settings import SettingsUpdate, get_settings, update_settings


def test_get_settings_reflects_current_ai_model_default(db):
    result = get_settings(db)
    assert result["ai_model"]  # never blank - always has at least the built-in default


def test_update_settings_changes_ai_model(db):
    update_settings(SettingsUpdate(ai_model="gemini-3.6-flash"), db)
    assert runtime_config.AI_MODEL == "gemini-3.6-flash"
    result = get_settings(db)
    assert result["ai_model"] == "gemini-3.6-flash"


def test_ai_model_survives_a_reload_simulating_a_restart(db):
    update_settings(SettingsUpdate(ai_model="some-future-model-name"), db)
    runtime_config.AI_MODEL = "gemini-3.6-flash"  # simulate a fresh process before load_from_db runs
    runtime_config.load_from_db(db)
    assert runtime_config.AI_MODEL == "some-future-model-name"


def test_update_settings_does_not_touch_ai_model_when_not_provided(db):
    update_settings(SettingsUpdate(ai_model="gemini-3.6-flash"), db)
    update_settings(SettingsUpdate(gemini_api_key="AIza-something"), db)
    assert runtime_config.AI_MODEL == "gemini-3.6-flash"
