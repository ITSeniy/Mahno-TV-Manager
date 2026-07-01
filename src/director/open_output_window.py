"""CLI: opens the local output window for the current OBS session.

Run this once after starting OBS (or again if the window gets closed) -
it's deliberately not part of run_playout.py's startup, since a crash/
restart of the director shouldn't spawn a new window every time. supervisor.py
also calls this once when it starts, for the same reason.

Usage:
    OBS_WS_PASSWORD=... .venv/Scripts/python.exe -m director.open_output_window
"""

from director.obs_client import get_client
from director.output_window import open_program_projector


def main() -> None:
    client = get_client()
    open_program_projector(client)
    print("Output window opened.")


if __name__ == "__main__":
    main()
