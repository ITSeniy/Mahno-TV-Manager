"""Spike: verify we can drive OBS from Python over obs-websocket.

Prerequisites:
  1. OBS Studio running.
  2. Tools -> WebSocket Server Settings -> "Enable WebSocket server" checked.
  3. Note the port (default 4455) and password (or disable auth for local testing).
  4. Set env vars before running:
       OBS_WS_PASSWORD=<password>   (OBS_WS_HOST/OBS_WS_PORT only if non-default)

Usage:
    .venv/Scripts/python.exe spikes/obs_connect.py [scene_name_to_switch_to]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from director.obs_client import get_client


def main() -> None:
    client = get_client()

    version = client.get_version()
    print(f"Connected: OBS {version.obs_version}, websocket protocol {version.obs_web_socket_version}")

    scenes = client.get_scene_list()
    print(f"Current scene: {scenes.current_program_scene_name}")
    print("Available scenes:")
    for scene in scenes.scenes:
        print(f"  - {scene['sceneName']}")

    if len(sys.argv) > 1:
        target = sys.argv[1]
        print(f"Switching to scene: {target}")
        client.set_current_program_scene(target)
        print("Done.")


if __name__ == "__main__":
    main()
