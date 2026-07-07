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

from director.vhs_effect import NTSC_FILTER_NAME, VHS_FILTER_NAME

ON_AIR_SCENE = "ON_AIR"
OFF_AIR_SCENE = "OFF_AIR"
SMS_CHAT_SCENE = "SMS_CHAT"
MEDIA_SOURCE = "program_player"
OFF_AIR_BG_SOURCE = "off_air_background"
OFF_AIR_TEXT_SOURCE = "off_air_label"
SMS_CHAT_SOURCE = "sms_chat_browser"

RESTART_ACTION = "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"

_ALIGN_TOP_LEFT = 5


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


def _scene_item_id(client: obsws.ReqClient, scene_name: str, source_name: str) -> int:
    for item in client.get_scene_item_list(scene_name).scene_items:
        if item["sourceName"] == source_name:
            return item["sceneItemId"]
    raise RuntimeError(f"scene item '{source_name}' not found in scene '{scene_name}'")


def _ensure_media_source_fills_canvas(client: obsws.ReqClient) -> None:
    """Library files come in wildly inconsistent native resolutions/aspect
    ratios (anamorphic DVD masters, VHS captures with inconsistently cropped
    frame edges, mixed NTSC/PAL/HD sources) - left at OBS's default 1:1
    sizing, each one letterboxes or pillarboxes by a different amount.
    Stretching every source to exactly fill the canvas (NTSC SD 720x480, read
    live from GetVideoSettings) trades a little aspect distortion (mild, since
    nearly everything here is already close to 4:3) for zero black bars ever,
    on any file, without needing to special-case any of them.

    Unlike overlays.py's hands-off-after-creation sources, this is a
    correctness fix rather than a look a user might want to hand-tune per
    file, so it's unconditionally reapplied every time the director starts
    rather than only when the source is first created.
    """
    video = client.get_video_settings()
    item_id = _scene_item_id(client, ON_AIR_SCENE, MEDIA_SOURCE)
    client.set_scene_item_transform(
        ON_AIR_SCENE,
        item_id,
        {
            "boundsType": "OBS_BOUNDS_STRETCH",
            "boundsAlignment": _ALIGN_TOP_LEFT,
            "boundsWidth": video.base_width,
            "boundsHeight": video.base_height,
            "alignment": _ALIGN_TOP_LEFT,
            "positionX": 0,
            "positionY": 0,
        },
    )


def ensure_scenes(client: obsws.ReqClient) -> None:
    scenes = _scene_names(client)

    if ON_AIR_SCENE not in scenes:
        client.create_scene(ON_AIR_SCENE)
    if MEDIA_SOURCE not in _input_names(client):
        media_kind = _resolve_kind(client, "ffmpeg_source")
        client.create_input(ON_AIR_SCENE, MEDIA_SOURCE, media_kind, {}, True)
    _ensure_media_source_fills_canvas(client)

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


def ensure_sms_scene(client: obsws.ReqClient, url: str) -> None:
    """Full-frame browser source for the night SMS-chat scene, pointed at the
    ticker server's /sms page. The schedule switches to this scene for the
    04:00-05:00 sms_chat block (see apply_item). Created once; not re-touched, so
    manual tweaks in OBS survive restarts (same policy as overlays)."""
    if SMS_CHAT_SCENE not in _scene_names(client):
        client.create_scene(SMS_CHAT_SCENE)
    if SMS_CHAT_SOURCE not in _input_names(client):
        video = client.get_video_settings()
        browser_kind = _resolve_kind(client, "browser_source")
        client.create_input(
            SMS_CHAT_SCENE, SMS_CHAT_SOURCE, browser_kind,
            {"url": url, "width": video.base_width, "height": video.base_height}, True,
        )


def apply_item(client: obsws.ReqClient, item_type: str, file_path: str | None, is_ntsc_rendered: bool) -> None:
    if item_type == "off_air":
        client.set_current_program_scene(OFF_AIR_SCENE)
        return
    if item_type == "sms_chat":
        client.set_current_program_scene(SMS_CHAT_SCENE)
        return

    client.set_input_settings(MEDIA_SOURCE, {"local_file": file_path, "is_local_file": True}, True)
    client.trigger_media_input_action(MEDIA_SOURCE, RESTART_ACTION)
    # ntsc-rs (offline pre-render, see ntsc_render.py) already baked the
    # analog VHS/NTSC look into this file if is_ntsc_rendered is True -
    # leaving the live filters on top would double-degrade the image. They
    # stay enabled only as a fallback for files that haven't been
    # pre-rendered yet, so nothing airs completely undegraded.
    # ensure_vhs_effect (vhs_effect.py) attaches these filters to the ON_AIR
    # *scene*, not the program_player source - toggling them on the wrong
    # object 600s with "no filter found".
    for filter_name in (NTSC_FILTER_NAME, VHS_FILTER_NAME):
        client.set_source_filter_enabled(ON_AIR_SCENE, filter_name, not is_ntsc_rendered)
    client.set_current_program_scene(ON_AIR_SCENE)
