"""Drives OBS scenes/sources to match whatever the schedule says is on air.

Bootstraps a minimal scene/source setup on first run if it isn't there yet:
  - scene ON_AIR with a media source PROGRAM_PLAYER, used for episodes/ads/bumpers
  - scene OFF_AIR with a plain color background + text label - a placeholder
    until real off-air artwork (VHS-style test card etc., Phase 5) exists

Input kind names (e.g. the versioned "text_gdiplus_v3") vary across OBS
releases, so they're resolved dynamically via GetInputKindList rather than
hardcoded.
"""

import obsws_python as obsws

ON_AIR_SCENE = "ON_AIR"
OFF_AIR_SCENE = "OFF_AIR"
MEDIA_SOURCE = "program_player"
OFF_AIR_BG_SOURCE = "off_air_background"
OFF_AIR_TEXT_SOURCE = "off_air_label"

RESTART_ACTION = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"


def _resolve_kind(client: obsws.ReqClient, *name_prefixes: str) -> str:
    # unversioned=True returns display-friendly names (e.g. "color_source") that
    # CreateInput rejects with error 605; the real usable kind id needs the
    # version suffix (e.g. "color_source_v3"), which only unversioned=False gives.
    kinds = client.get_input_kind_list(False).input_kinds
    for prefix in name_prefixes:
        for kind in kinds:
            if kind.startswith(prefix):
                return kind
    raise RuntimeError(f"No OBS input kind found matching any of {name_prefixes}; available: {kinds}")


def _scene_names(client: obsws.ReqClient) -> set[str]:
    return {s["sceneName"] for s in client.get_scene_list().scenes}


def _input_names(client: obsws.ReqClient) -> set[str]:
    return {i["inputName"] for i in client.get_input_list().inputs}


def ensure_scenes(client: obsws.ReqClient) -> None:
    scenes = _scene_names(client)

    if ON_AIR_SCENE not in scenes:
        client.create_scene(ON_AIR_SCENE)
    if MEDIA_SOURCE not in _input_names(client):
        media_kind = _resolve_kind(client, "ffmpeg_source")
        client.create_input(ON_AIR_SCENE, MEDIA_SOURCE, media_kind, {}, True)

    if OFF_AIR_SCENE not in scenes:
        client.create_scene(OFF_AIR_SCENE)
    inputs = _input_names(client)
    if OFF_AIR_BG_SOURCE not in inputs:
        color_kind = _resolve_kind(client, "color_source")
        client.create_input(OFF_AIR_SCENE, OFF_AIR_BG_SOURCE, color_kind, {"color": 0xFF1A1A2E}, True)
    if OFF_AIR_TEXT_SOURCE not in inputs:
        text_kind = _resolve_kind(client, "text_gdiplus", "text_ft2_source")
        client.create_input(
            OFF_AIR_SCENE,
            OFF_AIR_TEXT_SOURCE,
            text_kind,
            {"text": "ТЕХНИЧЕСКИЙ ПЕРЕРЫВ\n05:00 - 10:00 МСК"},
            True,
        )


def apply_item(client: obsws.ReqClient, item_type: str, file_path: str | None) -> None:
    if item_type == "off_air":
        client.set_current_program_scene(OFF_AIR_SCENE)
        return

    client.set_input_settings(MEDIA_SOURCE, {"local_file": file_path, "is_local_file": True}, True)
    client.trigger_media_input_action(MEDIA_SOURCE, RESTART_ACTION)
    client.set_current_program_scene(ON_AIR_SCENE)
