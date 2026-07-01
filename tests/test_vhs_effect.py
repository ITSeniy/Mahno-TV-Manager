from types import SimpleNamespace

from director.vhs_effect import (
    FILTER_CHAIN,
    FILTER_KIND,
    NTSC_FILTER_NAME,
    SCANLINES_FILTER_NAME,
    VHS_FILTER_NAME,
    ensure_vhs_effect,
)


class FakeObsClient:
    def __init__(self, existing_filters=()):
        self.filters = list(existing_filters)
        self.created = []  # (scene, filter_name, kind, settings)
        self.indices = {}

    def get_source_filter_list(self, name):
        return SimpleNamespace(filters=[{"filterName": f} for f in self.filters])

    def create_source_filter(self, source_name, filter_name, filter_kind, filter_settings=None):
        self.filters.append(filter_name)
        self.created.append((source_name, filter_name, filter_kind, filter_settings))

    def set_source_filter_index(self, source_name, filter_name, filter_index):
        self.indices[filter_name] = filter_index


def test_ensure_vhs_effect_creates_the_full_chain_in_order():
    client = FakeObsClient()
    ensure_vhs_effect(client, "ON_AIR")

    created_names = [c[1] for c in client.created]
    assert created_names == [NTSC_FILTER_NAME, VHS_FILTER_NAME, SCANLINES_FILTER_NAME]
    assert all(c[0] == "ON_AIR" for c in client.created)
    assert all(c[2] == FILTER_KIND for c in client.created)

    assert client.indices == {NTSC_FILTER_NAME: 0, VHS_FILTER_NAME: 1, SCANLINES_FILTER_NAME: 2}


def test_ensure_vhs_effect_settings_match_the_configured_filter_type():
    client = FakeObsClient()
    ensure_vhs_effect(client, "ON_AIR")

    settings_by_name = {c[1]: c[3] for c in client.created}
    for filter_name, expected_settings in FILTER_CHAIN:
        assert settings_by_name[filter_name] == expected_settings


def test_ensure_vhs_effect_is_idempotent_when_everything_exists():
    client = FakeObsClient(existing_filters=[NTSC_FILTER_NAME, VHS_FILTER_NAME, SCANLINES_FILTER_NAME])
    ensure_vhs_effect(client, "ON_AIR")

    assert client.created == []
    assert client.indices == {}


def test_ensure_vhs_effect_only_creates_missing_filters_and_leaves_others_alone():
    client = FakeObsClient(existing_filters=[NTSC_FILTER_NAME])
    ensure_vhs_effect(client, "ON_AIR")

    created_names = [c[1] for c in client.created]
    assert NTSC_FILTER_NAME not in created_names
    assert created_names == [VHS_FILTER_NAME, SCANLINES_FILTER_NAME]
