"""Thin wrapper around obsws-python for connecting to a running OBS instance.

Connection parameters, in order of priority:

    OBS_WS_HOST / OBS_WS_PORT / OBS_WS_PASSWORD   environment variables
    secrets.json's "obs_ws_password"              fallback for the password,
                                                    so launcher scripts don't
                                                    need to embed or prompt
                                                    for it every time

Host/port default to localhost:4455 (OBS 28+ default) if nothing is set.
"""

import os

import obsws_python as obsws

from director.config import Secrets


def _default_password() -> str:
    env_password = os.environ.get("OBS_WS_PASSWORD")
    if env_password:
        return env_password
    try:
        return Secrets.load().obs_ws_password or ""
    except FileNotFoundError:
        return ""


def get_client() -> obsws.ReqClient:
    host = os.environ.get("OBS_WS_HOST", "localhost")
    port = int(os.environ.get("OBS_WS_PORT", "4455"))
    password = _default_password()
    return obsws.ReqClient(host=host, port=port, password=password, timeout=5)
