from types import SimpleNamespace

from director.overlays import (
    LOGO_BOX_HEIGHT,
    LOGO_BOX_WIDTH,
    LOGO_MARGIN,
    LOGO_SOURCE,
    TICKER_HEIGHT,
    TICKER_SOURCE,
    ensure_logo,
    ensure_ticker_source,
)


class FakeObsClient:
    def __init__(self, existing_inputs=(), base_width=1920, base_height=1080):
        self.inputs = list(existing_inputs)
        self.base_width = base_width
        self.base_height = base_height
        self.input_settings = {}
        self.transforms = {}
        self._next_item_id = 1
        self.item_ids = {}  # input_name -> scene_item_id

    def get_input_list(self, kind=None):
        return SimpleNamespace(inputs=[{"inputName": i} for i in self.inputs])

    def get_video_settings(self):
        return SimpleNamespace(base_width=self.base_width, base_height=self.base_height)

    def create_input(self, scene_name, input_name, input_kind, input_settings, scene_item_enabled):
        self.inputs.append(input_name)
        self.input_settings[input_name] = input_settings
        self.item_ids[input_name] = self._next_item_id
        self._next_item_id += 1

    def set_input_settings(self, name, settings, overlay):
        self.input_settings[name] = settings

    def get_scene_item_list(self, scene_name):
        return SimpleNamespace(
            scene_items=[{"sourceName": name, "sceneItemId": iid} for name, iid in self.item_ids.items()]
        )

    def set_scene_item_transform(self, scene_name, item_id, transform):
        self.transforms[item_id] = transform


def test_ensure_logo_creates_and_positions_bottom_right():
    client = FakeObsClient()
    ensure_logo(client, "ON_AIR", "C:/branding/logo.png")

    assert LOGO_SOURCE in client.inputs
    assert client.input_settings[LOGO_SOURCE] == {"file": "C:/branding/logo.png"}

    item_id = client.item_ids[LOGO_SOURCE]
    transform = client.transforms[item_id]
    assert transform["boundsWidth"] == LOGO_BOX_WIDTH
    assert transform["boundsHeight"] == LOGO_BOX_HEIGHT
    assert transform["positionX"] == 1920 - LOGO_BOX_WIDTH - LOGO_MARGIN
    assert transform["positionY"] == 1080 - LOGO_BOX_HEIGHT - LOGO_MARGIN


def test_ensure_logo_updates_existing_source_instead_of_recreating():
    client = FakeObsClient(existing_inputs=[LOGO_SOURCE])
    client.item_ids[LOGO_SOURCE] = 7

    ensure_logo(client, "ON_AIR", "C:/branding/new_logo.png")

    assert client.inputs.count(LOGO_SOURCE) == 1  # not duplicated
    assert client.input_settings[LOGO_SOURCE] == {"file": "C:/branding/new_logo.png"}
    assert 7 in client.transforms


def test_ensure_ticker_source_spans_full_width_and_sits_at_bottom():
    client = FakeObsClient()
    ensure_ticker_source(client, "ON_AIR", "http://127.0.0.1:8765/")

    assert TICKER_SOURCE in client.inputs
    assert client.input_settings[TICKER_SOURCE] == {
        "url": "http://127.0.0.1:8765/",
        "width": 1920,
        "height": TICKER_HEIGHT,
    }

    item_id = client.item_ids[TICKER_SOURCE]
    transform = client.transforms[item_id]
    assert transform["positionX"] == 0
    assert transform["positionY"] == 1080 - TICKER_HEIGHT


def test_ensure_ticker_source_adapts_to_a_different_canvas_size():
    client = FakeObsClient(base_width=1280, base_height=720)
    ensure_ticker_source(client, "ON_AIR", "http://127.0.0.1:8765/")

    assert client.input_settings[TICKER_SOURCE]["width"] == 1280
    item_id = client.item_ids[TICKER_SOURCE]
    assert client.transforms[item_id]["positionY"] == 720 - TICKER_HEIGHT
