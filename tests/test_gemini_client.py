from google.genai import errors

from director import gemini_client


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """Stands in for genai.Client - behavior maps (model, api_key) -> a
    FakeResponse to return or an Exception to raise."""

    def __init__(self, api_key, behavior):
        self.api_key = api_key
        self.behavior = behavior
        self.models = self

    def generate_content(self, model, contents):
        outcome = self.behavior[(model, self.api_key)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def patch_client(monkeypatch, behavior):
    monkeypatch.setattr(gemini_client.genai, "Client", lambda api_key: FakeClient(api_key, behavior))


def rate_limited():
    return errors.APIError(429, {"error": {"message": "rate limited"}})


def test_uses_the_preferred_model_and_first_key_when_it_works(monkeypatch):
    behavior = {
        ("gemini-3.5-flash", "key1"): FakeResponse("ГОТОВЫЕ СТРОКИ"),
    }
    patch_client(monkeypatch, behavior)

    result = gemini_client.generate_text(["key1"], "prompt")
    assert result == "ГОТОВЫЕ СТРОКИ"


def test_falls_back_to_next_key_on_the_same_model_when_rate_limited(monkeypatch):
    behavior = {
        ("gemini-3.5-flash", "key1"): rate_limited(),
        ("gemini-3.5-flash", "key2"): FakeResponse("FROM KEY2"),
    }
    patch_client(monkeypatch, behavior)

    result = gemini_client.generate_text(["key1", "key2"], "prompt")
    assert result == "FROM KEY2"


def test_falls_back_to_the_cheaper_model_when_all_keys_exhausted_on_preferred(monkeypatch):
    behavior = {
        ("gemini-3.5-flash", "key1"): rate_limited(),
        ("gemini-3.5-flash", "key2"): rate_limited(),
        ("gemini-3.1-flash-lite", "key1"): FakeResponse("FROM LITE"),
    }
    patch_client(monkeypatch, behavior)

    result = gemini_client.generate_text(["key1", "key2"], "prompt")
    assert result == "FROM LITE"


def test_raises_when_every_combination_fails(monkeypatch):
    behavior = {
        ("gemini-3.5-flash", "key1"): rate_limited(),
        ("gemini-3.1-flash-lite", "key1"): rate_limited(),
    }
    patch_client(monkeypatch, behavior)

    try:
        gemini_client.generate_text(["key1"], "prompt")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "exhausted" in str(exc)


def test_treats_empty_response_text_as_a_failure_and_keeps_trying(monkeypatch):
    behavior = {
        ("gemini-3.5-flash", "key1"): FakeResponse(""),
        ("gemini-3.5-flash", "key2"): FakeResponse("ACTUAL TEXT"),
    }
    patch_client(monkeypatch, behavior)

    result = gemini_client.generate_text(["key1", "key2"], "prompt")
    assert result == "ACTUAL TEXT"


def test_raises_immediately_with_no_keys_configured():
    try:
        gemini_client.generate_text([], "prompt")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "No Gemini API keys" in str(exc)
