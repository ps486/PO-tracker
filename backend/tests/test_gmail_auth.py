"""Covers the Gmail OAuth flow builder. Verifies the fix for a real bug: two
separate Flow instances (one to build the authorization URL, one - in a
later, separate HTTP request - to exchange the code for tokens) don't share
state, so the library's default auto-generated PKCE code_verifier from the
first instance never reaches the second, and Google rejects the token
exchange with "invalid_grant: Missing code verifier". Since this is a
confidential client (has a client secret), PKCE isn't required, so it's
disabled instead of trying to persist the verifier across requests."""
from backend.app import runtime_config
from backend.app.gmail.auth import build_flow


def _configure_fake_credentials(monkeypatch):
    monkeypatch.setattr(runtime_config, "GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr(runtime_config, "GOOGLE_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr(runtime_config, "GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/gmail/callback")


def test_authorization_url_has_no_pkce_code_challenge(monkeypatch):
    _configure_fake_credentials(monkeypatch)
    flow = build_flow()
    url, _state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    assert "code_challenge" not in url


def test_flow_has_no_code_verifier_after_building_url(monkeypatch):
    _configure_fake_credentials(monkeypatch)
    flow = build_flow()
    flow.authorization_url()
    # If this were non-None, a *different* Flow instance built later (as
    # happens for real: authorize and callback are separate HTTP requests)
    # would have no way to know it, which is exactly the bug being fixed.
    assert flow.code_verifier is None


def test_two_separate_flow_instances_stay_consistent(monkeypatch):
    """Simulates the real authorize-then-callback sequence: two independently
    constructed Flow objects, as would happen across two separate requests."""
    _configure_fake_credentials(monkeypatch)
    authorize_flow = build_flow()
    authorize_flow.authorization_url()

    callback_flow = build_flow(state="some-state")
    # Neither flow ever generated a verifier, so there's nothing for the
    # callback's token exchange to be missing/mismatched against.
    assert authorize_flow.code_verifier is None
    assert callback_flow.code_verifier is None
