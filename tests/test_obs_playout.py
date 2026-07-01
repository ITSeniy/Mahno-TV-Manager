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


class FakeObsClient:
    def __init__(self, existing_scenes=(), existing_inputs=()):
        self.scenes = list(existing_scenes)
        self.inputs = list(existing_inputs)
        self.calls = []
        self.current_scene = None
        self.input_settings = {}

    def get_scene_list(self):
        return SimpleNamespace(scenes=[{"sceneName": s} for s in self.scenes])

    def get_input_list(self, kind=None):
        return SimpleNamespace(inputs=[{"inputName": i} for i in self.inputs])

    def get_input_kind_list(self, unversioned):
        return SimpleNamespace(
            input_kinds=["ffmpeg_source", "color_source_v3", "text_gdiplus_v3", "image_source"]
        )

    def create_scene(self, name):
        self.calls.append(("create_scene", name))
        self.scenes.append(name)

    def create_input(self, scene_name, input_name, input_kind, input_settings, scene_item_enabled):
        self.calls.append(("create_input", scene_name, input_name, input_kind))
        self.inputs.append(input_name)

    def set_input_settings(self, name, settings, overlay):
        self.calls.append(("set_input_settings", name, settings, overlay))
        self.input_settings[name] = settings

    def trigger_media_input_action(self, name, action):
        self.calls.append(("trigger_media_input_action", name, action))

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


def test_ensure_scenes_is_idempotent_when_everything_already_exists():
    client = FakeObsClient(
        existing_scenes=[ON_AIR_SCENE, OFF_AIR_SCENE],
        existing_inputs=[MEDIA_SOURCE, OFF_AIR_BG_SOURCE, OFF_AIR_TEXT_SOURCE],
    )
    ensure_scenes(client)

    assert client.calls == []  # nothing created a second time


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


def test_apply_item_for_episode_sets_file_restarts_and_switches_to_on_air():
    client = FakeObsClient()
    apply_item(client, "episode", "/library/show/e1.mkv")

    assert client.input_settings[MEDIA_SOURCE] == {"local_file": "/library/show/e1.mkv", "is_local_file": True}
    assert ("trigger_media_input_action", MEDIA_SOURCE, RESTART_ACTION) in client.calls
    assert client.current_scene == ON_AIR_SCENE


def test_apply_item_for_off_air_switches_scene_without_touching_media_source():
    client = FakeObsClient()
    apply_item(client, "off_air", None)

    assert client.current_scene == OFF_AIR_SCENE
    assert MEDIA_SOURCE not in client.input_settings
    assert not any(c[0] == "trigger_media_input_action" for c in client.calls)
