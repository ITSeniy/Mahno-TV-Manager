"""Opens a local windowed projector showing OBS's live Program output.

This is a one-time-per-OBS-session action, not part of run_playout.py's
startup bootstrap: unlike scenes/sources/filters, a projector window isn't a
persistent OBS object saved to the scene collection, so calling this on
every director restart would pile up duplicate windows even though OBS
itself never restarted.
"""

import obsws_python as obsws

PROGRAM_MIX_TYPE = "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM"


def open_program_projector(client: obsws.ReqClient) -> None:
    client.open_video_mix_projector(PROGRAM_MIX_TYPE)
