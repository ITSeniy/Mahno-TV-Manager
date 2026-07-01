from types import SimpleNamespace

from director.vst_audio import CHOWTAPE_VST2_PATH, FILTER_KIND, TAPE_FILTER_NAME, ensure_tape_effect


class FakeObsClient:
    def __init__(self, existing_filters=()):
        self.filters = list(existing_filters)
        self.created = []  # (source, filter_name, kind, settings)

    def get_source_filter_list(self, name):
        return SimpleNamespace(filters=[{"filterName": f} for f in self.filters])

    def create_source_filter(self, source_name, filter_name, filter_kind, filter_settings=None):
        self.filters.append(filter_name)
        self.created.append((source_name, filter_name, filter_kind, filter_settings))


def test_ensure_tape_effect_creates_the_vst_filter_with_the_plugin_path():
    client = FakeObsClient()
    ensure_tape_effect(client, "program_player")

    assert TAPE_FILTER_NAME in client.filters
    source, name, kind, settings = client.created[0]
    assert source == "program_player"
    assert kind == FILTER_KIND
    assert settings == {"plugin_path": CHOWTAPE_VST2_PATH}


def test_ensure_tape_effect_accepts_a_custom_plugin_path():
    client = FakeObsClient()
    ensure_tape_effect(client, "program_player", plugin_path="D:/VST/Other.dll")

    assert client.created[0][3] == {"plugin_path": "D:/VST/Other.dll"}


def test_ensure_tape_effect_is_idempotent():
    client = FakeObsClient(existing_filters=[TAPE_FILTER_NAME])
    ensure_tape_effect(client, "program_player")

    assert client.created == []
