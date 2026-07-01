"""Thin wrapper around obsws-python for connecting to a running OBS instance.

Connection parameters come from environment variables so the same code works
on any machine without hardcoding credentials:

    OBS_WS_HOST      default "localhost"
    OBS_WS_PORT      default 4455 (OBS 28+ default)
    OBS_WS_PASSWORD  required unless the OBS websocket server has auth disabled
"""

import os

import obsws_python as obsws


def get_client() -> obsws.ReqClient:
    host = os.environ.get("OBS_WS_HOST", "localhost")
    port = int(os.environ.get("OBS_WS_PORT", "4455"))
    password = os.environ.get("OBS_WS_PASSWORD", "")
    return obsws.ReqClient(host=host, port=port, password=password, timeout=5)
