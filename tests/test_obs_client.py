from director.config import Secrets
from director.obs_client import _default_password


def test_env_var_takes_priority_over_secrets_file(monkeypatch):
    monkeypatch.setenv("OBS_WS_PASSWORD", "from-env")
    monkeypatch.setattr(
        "director.obs_client.Secrets.load", lambda: Secrets(gemini_api_keys=[], obs_ws_password="from-secrets")
    )
    assert _default_password() == "from-env"


def test_falls_back_to_secrets_file_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("OBS_WS_PASSWORD", raising=False)
    monkeypatch.setattr(
        "director.obs_client.Secrets.load", lambda: Secrets(gemini_api_keys=[], obs_ws_password="from-secrets")
    )
    assert _default_password() == "from-secrets"


def test_falls_back_to_empty_string_when_secrets_file_is_missing(monkeypatch):
    monkeypatch.delenv("OBS_WS_PASSWORD", raising=False)

    def raise_not_found():
        raise FileNotFoundError("no secrets.json")

    monkeypatch.setattr("director.obs_client.Secrets.load", lambda: raise_not_found())
    assert _default_password() == ""


def test_falls_back_to_empty_string_when_secrets_file_has_no_obs_password(monkeypatch):
    monkeypatch.delenv("OBS_WS_PASSWORD", raising=False)
    monkeypatch.setattr(
        "director.obs_client.Secrets.load", lambda: Secrets(gemini_api_keys=[], obs_ws_password=None)
    )
    assert _default_password() == ""
