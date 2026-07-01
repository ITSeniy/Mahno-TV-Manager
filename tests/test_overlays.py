from types import SimpleNamespace

from director.overlays import (
    LOGO_HEIGHT_FRACTION,
    LOGO_MARGIN_FRACTION,
    LOGO_SOURCE,
    LOGO_WIDTH_FRACTION,
    TICKER_HEIGHT_FRACTION,
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
        # Mirrors real OBS semantics: overlay=True merges onto existing settings
        # instead of replacing them wholesale.
        if overlay and name in self.input_settings:
            self.input_settings[name] = {**self.input_settings[name], **settings}
        else:
            self.input_settings[name] = settings

    def get_scene_item_list(self, scene_name):
        return SimpleNamespace(
            scene_items=[{"sourceName": name, "sceneItemId": iid} for name, iid in self.item_ids.items()]
        )

    def set_scene_item_transform(self, scene_name, item_id, transform):
        self.transforms[item_id] = transform


def test_ensure_logo_creates_and_positions_bottom_right():
    client = FakeObsClient(base_width=1920, base_height=1080)
    ensure_logo(client, "ON_AIR", "C:/branding/logo.png")

    assert LOGO_SOURCE in client.inputs
    assert client.input_settings[LOGO_SOURCE] == {"file": "C:/branding/logo.png"}

    box_width = round(1920 * LOGO_WIDTH_FRACTION)
    box_height = round(1080 * LOGO_HEIGHT_FRACTION)
    margin_x = round(1920 * LOGO_MARGIN_FRACTION)
    margin_y = round(1080 * LOGO_MARGIN_FRACTION)

    item_id = client.item_ids[LOGO_SOURCE]
    transform = client.transforms[item_id]
    assert transform["boundsWidth"] == box_width
    assert transform["boundsHeight"] == box_height
    assert transform["positionX"] == 1920 - box_width - margin_x
    assert transform["positionY"] == 1080 - box_height - margin_y


def test_ensure_logo_scales_down_for_a_small_pal_canvas():
    client = FakeObsClient(base_width=720, base_height=576)
    ensure_logo(client, "ON_AIR", "C:/branding/logo.png")

    box_width = round(720 * LOGO_WIDTH_FRACTION)
    box_height = round(576 * LOGO_HEIGHT_FRACTION)
    item_id = client.item_ids[LOGO_SOURCE]
    transform = client.transforms[item_id]

    assert transform["boundsWidth"] == box_width
    assert transform["boundsHeight"] == box_height
    # A box sized for 1920x1080 (220px) would swallow ~30% of a 720-wide canvas -
    # the fraction-based box must stay proportionally small instead.
    assert box_width < 720 * 0.2


def test_ensure_logo_resyncs_file_but_leaves_a_hand_tuned_layout_alone():
    client = FakeObsClient(existing_inputs=[LOGO_SOURCE])
    client.item_ids[LOGO_SOURCE] = 7

    ensure_logo(client, "ON_AIR", "C:/branding/new_logo.png")

    assert client.inputs.count(LOGO_SOURCE) == 1  # not duplicated
    assert client.input_settings[LOGO_SOURCE] == {"file": "C:/branding/new_logo.png"}
    # No transform call at all - someone may have hand-positioned this in OBS
    # since it was created, and a restart of the director must not reset it.
    assert client.transforms == {}


def test_ensure_ticker_source_spans_full_width_and_sits_at_bottom():
    client = FakeObsClient(base_width=1920, base_height=1080)
    ensure_ticker_source(client, "ON_AIR", "http://127.0.0.1:8765/")

    height = round(1080 * TICKER_HEIGHT_FRACTION)
    assert TICKER_SOURCE in client.inputs
    assert client.input_settings[TICKER_SOURCE] == {
        "url": "http://127.0.0.1:8765/",
        "width": 1920,
        "height": height,
    }

    item_id = client.item_ids[TICKER_SOURCE]
    transform = client.transforms[item_id]
    assert transform["positionX"] == 0
    assert transform["positionY"] == 1080 - height


def test_ensure_ticker_source_adapts_to_a_different_canvas_size():
    client = FakeObsClient(base_width=720, base_height=576)
    ensure_ticker_source(client, "ON_AIR", "http://127.0.0.1:8765/")

    height = round(576 * TICKER_HEIGHT_FRACTION)
    assert client.input_settings[TICKER_SOURCE]["width"] == 720
    assert client.input_settings[TICKER_SOURCE]["height"] == height
    item_id = client.item_ids[TICKER_SOURCE]
    assert client.transforms[item_id]["positionY"] == 576 - height


def test_ensure_ticker_source_only_resyncs_url_for_an_existing_source():
    client = FakeObsClient(existing_inputs=[TICKER_SOURCE], base_width=720, base_height=576)
    client.item_ids[TICKER_SOURCE] = 9
    client.input_settings[TICKER_SOURCE] = {"url": "http://old", "width": 500, "height": 40}

    ensure_ticker_source(client, "ON_AIR", "http://127.0.0.1:8765/")

    # Only the URL is resynced (merged, not replaced) - a hand-adjusted
    # size/position must survive a restart.
    assert client.input_settings[TICKER_SOURCE] == {"url": "http://127.0.0.1:8765/", "width": 500, "height": 40}
    assert client.transforms == {}
