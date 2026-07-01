"""Logo and ticker overlay sources, layered on top of the ON_AIR scene.

The logo is pinned to the bottom-right corner (classic channel "bug") using
OBS's bounds-scaling so it looks right regardless of the source image's
native resolution - no need to know the logo's pixel size ahead of time.
"""

import obsws_python as obsws

LOGO_SOURCE = "channel_logo"
TICKER_SOURCE = "ticker_overlay"

LOGO_BOX_WIDTH = 220
LOGO_BOX_HEIGHT = 110
LOGO_MARGIN = 24

TICKER_HEIGHT = 60

_ALIGN_TOP_LEFT = 5
_ALIGN_CENTER = 0


def _input_names(client: obsws.ReqClient) -> set[str]:
    return {i["inputName"] for i in client.get_input_list().inputs}


def _scene_item_id(client: obsws.ReqClient, scene_name: str, source_name: str) -> int:
    for item in client.get_scene_item_list(scene_name).scene_items:
        if item["sourceName"] == source_name:
            return item["sceneItemId"]
    raise RuntimeError(f"scene item '{source_name}' not found in scene '{scene_name}'")


def ensure_logo(client: obsws.ReqClient, scene_name: str, logo_path: str) -> None:
    if LOGO_SOURCE not in _input_names(client):
        client.create_input(scene_name, LOGO_SOURCE, "image_source", {"file": logo_path}, True)
    else:
        client.set_input_settings(LOGO_SOURCE, {"file": logo_path}, True)

    video = client.get_video_settings()
    item_id = _scene_item_id(client, scene_name, LOGO_SOURCE)
    client.set_scene_item_transform(
        scene_name,
        item_id,
        {
            "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "boundsAlignment": _ALIGN_CENTER,
            "boundsWidth": LOGO_BOX_WIDTH,
            "boundsHeight": LOGO_BOX_HEIGHT,
            "alignment": _ALIGN_TOP_LEFT,
            "positionX": video.base_width - LOGO_BOX_WIDTH - LOGO_MARGIN,
            "positionY": video.base_height - LOGO_BOX_HEIGHT - LOGO_MARGIN,
        },
    )


def ensure_ticker_source(client: obsws.ReqClient, scene_name: str, url: str) -> None:
    video = client.get_video_settings()
    settings = {"url": url, "width": video.base_width, "height": TICKER_HEIGHT}

    if TICKER_SOURCE not in _input_names(client):
        client.create_input(scene_name, TICKER_SOURCE, "browser_source", settings, True)
    else:
        client.set_input_settings(TICKER_SOURCE, settings, True)

    item_id = _scene_item_id(client, scene_name, TICKER_SOURCE)
    client.set_scene_item_transform(
        scene_name,
        item_id,
        {
            "boundsType": "OBS_BOUNDS_NONE",
            "alignment": _ALIGN_TOP_LEFT,
            "positionX": 0,
            "positionY": video.base_height - TICKER_HEIGHT,
        },
    )
