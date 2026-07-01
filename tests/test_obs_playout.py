"""Tests obs_playout.py against a fake obsws-python client (no real OBS
needed) - verifies the request sequence and idempotent bootstrapping, since
the actual OBS protocol behavior can only be confirmed against a live
instance (see the manual smoke test run against real OBS 32.0.4)."""

from types import SimpleNamespace

import pytest

from director.obs_playout import (
    MEDIA_SOURCE,
    OFF_AIR_BG_SOURCE,
    OFF_AIR_SCENE,
    OFF_AIR_TEXT_SOURCE,
    ON_AIR_SCENE,
    RESTART_ACTION,
    apply_item,
    ensure_scenes,
)
from director.vhs_effect import NTSC_FILTER_NAME, VHS_FILTER_NAME


class FakeObsClient:
    def __init__(
        self, existing_scenes=(), existing_inputs=(), base_width=720, base_height=576, existing_filters=()
    ):
        self.scenes = list(existing_scenes)
        self.inputs = list(existing_inputs)
        self.calls = []
        self.current_scene = None
        self.input_settings = {}
        self.base_width = base_width
        self.base_height = base_height
        self.transforms = {}  # scene_item_id -> transform dict
        self.item_ids = {}  # input_name -> scene_item_id
        self.filter_enabled = {}  # (source_name, filter_name) -> bool
        # (source_name, filter_name) pairs that "exist" in this fake OBS -
        # real OBS errors (code 600) if you try to enable/disable a filter
        # on a source it isn't actually attached to, which is exactly the
        # bug a live smoke test caught (toggling filters on program_player
        # when ensure_vhs_effect actually attaches them to the ON_AIR scene)
        # - a client that silently accepted any pair wouldn't have caught it.
        self.existing_filters = set(existing_filters)
        self._next_item_id = 1
        for existing in self.inputs:
            self.item_ids[existing] = self._next_item_id
            self._next_item_id += 1

    def get_scene_list(self):
        return SimpleNamespace(scenes=[{"sceneName": s} for s in self.scenes])

    def get_input_list(self, kind=None):
        return SimpleNamespace(inputs=[{"inputName": i} for i in self.inputs])

    def get_input_kind_list(self, unversioned):
        return SimpleNamespace(
            input_kinds=["ffmpeg_source", "color_source_v3", "text_gdiplus_v3", "image_source"]
        )

    def get_video_settings(self):
        return SimpleNamespace(base_width=self.base_width, base_height=self.base_height)

    def get_scene_item_list(self, scene_name):
        return SimpleNamespace(
            scene_items=[{"sourceName": name, "sceneItemId": iid} for name, iid in self.item_ids.items()]
        )

    def create_scene(self, name):
        self.calls.append(("create_scene", name))
        self.scenes.append(name)

    def create_input(self, scene_name, input_name, input_kind, input_settings, scene_item_enabled):
        self.calls.append(("create_input", scene_name, input_name, input_kind))
        self.inputs.append(input_name)
        self.item_ids[input_name] = self._next_item_id
        self._next_item_id += 1

    def set_input_settings(self, name, settings, overlay):
        self.calls.append(("set_input_settings", name, settings, overlay))
        self.input_settings[name] = settings

    def set_scene_item_transform(self, scene_name, item_id, transform):
        self.calls.append(("set_scene_item_transform", scene_name, item_id, transform))
        self.transforms[item_id] = transform

    def trigger_media_input_action(self, name, action):
        self.calls.append(("trigger_media_input_action", name, action))

    def set_source_filter_enabled(self, source_name, filter_name, enabled):
        if (source_name, filter_name) not in self.existing_filters:
            raise RuntimeError(
                f"Request SetSourceFilterEnabled returned code 600. With message: "
                f"No filter was found in the source `{source_name}` with the name `{filter_name}`."
            )
        self.calls.append(("set_source_filter_enabled", source_name, filter_name, enabled))
        self.filter_enabled[(source_name, filter_name)] = enabled

    def set_current_program_scene(self, name):
        self.calls.append(("set_current_program_scene", name))
        self.current_scene = name


def test_ensure_scenes_creates_everything_on_a_blank_obs():
    client = FakeObsClient()
    ensure_scenes(client)

    assert ON_AIR_SCENE in client.scenes
    assert OFF_AIR_SCENE in client.scenes
    assert MEDIA_SOURCE in client.inputs
    assert OFF_AIR_BG_SOURCE in client.inputs
    assert OFF_AIR_TEXT_SOURCE in client.inputs


def test_ensure_scenes_stretches_the_media_source_to_fill_the_canvas():
    client = FakeObsClient(base_width=720, base_height=576)
    ensure_scenes(client)

    item_id = client.item_ids[MEDIA_SOURCE]
    transform = client.transforms[item_id]
    assert transform["boundsType"] == "OBS_BOUNDS_STRETCH"
    assert transform["boundsWidth"] == 720
    assert transform["boundsHeight"] == 576
    assert transform["positionX"] == 0
    assert transform["positionY"] == 0


def test_ensure_scenes_media_source_stretch_tracks_canvas_size():
    client = FakeObsClient(base_width=1280, base_height=720)
    ensure_scenes(client)

    item_id = client.item_ids[MEDIA_SOURCE]
    transform = client.transforms[item_id]
    assert transform["boundsWidth"] == 1280
    assert transform["boundsHeight"] == 720


def test_ensure_scenes_is_idempotent_when_everything_already_exists():
    client = FakeObsClient(
        existing_scenes=[ON_AIR_SCENE, OFF_AIR_SCENE],
        existing_inputs=[MEDIA_SOURCE, OFF_AIR_BG_SOURCE, OFF_AIR_TEXT_SOURCE],
    )
    ensure_scenes(client)

    # Nothing gets (re-)created...
    assert not any(c[0] in ("create_scene", "create_input") for c in client.calls)
    # ...but the media source's fill-canvas transform is still (re-)applied
    # every time, unlike overlay positions - see _ensure_media_source_fills_canvas.
    assert any(c[0] == "set_scene_item_transform" for c in client.calls)


def test_ensure_scenes_only_creates_missing_pieces():
    client = FakeObsClient(existing_scenes=[ON_AIR_SCENE, OFF_AIR_SCENE], existing_inputs=[MEDIA_SOURCE])
    ensure_scenes(client)

    created_inputs = [c[2] for c in client.calls if c[0] == "create_input"]
    assert MEDIA_SOURCE not in created_inputs
    assert OFF_AIR_BG_SOURCE in created_inputs
    assert OFF_AIR_TEXT_SOURCE in created_inputs
    assert not any(c[0] == "create_scene" for c in client.calls)


def test_ensure_scenes_raises_clear_error_when_no_matching_kind_exists():
    client = FakeObsClient()
    client.get_input_kind_list = lambda unversioned: SimpleNamespace(input_kinds=["some_other_kind"])
    with pytest.raises(RuntimeError, match="ffmpeg_source"):
        ensure_scenes(client)


_NTSC_VHS_FILTERS_ON_ON_AIR_SCENE = {(ON_AIR_SCENE, NTSC_FILTER_NAME), (ON_AIR_SCENE, VHS_FILTER_NAME)}


def test_apply_item_for_episode_sets_file_restarts_and_switches_to_on_air():
    client = FakeObsClient(existing_filters=_NTSC_VHS_FILTERS_ON_ON_AIR_SCENE)
    apply_item(client, "episode", "/library/show/e1.mkv", True)

    assert client.input_settings[MEDIA_SOURCE] == {"local_file": "/library/show/e1.mkv", "is_local_file": True}
    assert ("trigger_media_input_action", MEDIA_SOURCE, RESTART_ACTION) in client.calls
    assert client.current_scene == ON_AIR_SCENE


def test_apply_item_for_off_air_switches_scene_without_touching_media_source():
    client = FakeObsClient()
    apply_item(client, "off_air", None, True)

    assert client.current_scene == OFF_AIR_SCENE
    assert MEDIA_SOURCE not in client.input_settings
    assert not any(c[0] == "trigger_media_input_action" for c in client.calls)


def test_apply_item_disables_live_ntsc_vhs_filters_when_ntsc_rs_already_rendered():
    # ensure_vhs_effect (vhs_effect.py) attaches these filters to the
    # ON_AIR scene, not the program_player source - toggling the wrong one
    # is exactly the bug a live-OBS smoke test caught (the fake client here
    # doesn't reject an unknown source/filter pair the way real OBS does,
    # so this assertion on the *target* is what actually guards against it).
    client = FakeObsClient(existing_filters=_NTSC_VHS_FILTERS_ON_ON_AIR_SCENE)
    apply_item(client, "episode", "/cache/episode/1.mp4", True)

    assert client.filter_enabled[(ON_AIR_SCENE, NTSC_FILTER_NAME)] is False
    assert client.filter_enabled[(ON_AIR_SCENE, VHS_FILTER_NAME)] is False


def test_apply_item_enables_live_ntsc_vhs_filters_as_fallback_when_not_rendered():
    client = FakeObsClient(existing_filters=_NTSC_VHS_FILTERS_ON_ON_AIR_SCENE)
    apply_item(client, "episode", "/library/show/e1.mkv", False)

    assert client.filter_enabled[(ON_AIR_SCENE, NTSC_FILTER_NAME)] is True
    assert client.filter_enabled[(ON_AIR_SCENE, VHS_FILTER_NAME)] is True


def test_apply_item_for_off_air_does_not_touch_ntsc_vhs_filters():
    client = FakeObsClient()
    apply_item(client, "off_air", None, True)

    assert client.filter_enabled == {}
