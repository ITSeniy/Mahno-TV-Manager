"""Analog/cassette-tape audio coloring via OBS's built-in VST 2.x host.

OBS only hosts VST2 natively (obs-vst.dll, filter kind "vst_filter") - VST3
needs a third-party bridge like atkAudio. CHOW Tape Model is installed as
both VST2 and VST3 locally; VST2 is used here to avoid that extra
dependency.

Same hands-off-after-creation rule as overlays.py/vhs_effect.py: the filter
is only created once. Tape saturation/wow-flutter amount is tuned inside
the plugin's own UI (OBS filter properties -> Open plugin interface), not
scripted here - a VST's parameter state is an opaque serialized "chunk"
that only really makes sense to set by hand once and leave alone
afterward.
"""

import obsws_python as obsws

FILTER_KIND = "vst_filter"
TAPE_FILTER_NAME = "chow_tape"
CHOWTAPE_VST2_PATH = r"C:\Program Files\Common Files\VST\CHOWTapeModel.dll"


def _existing_filter_names(client: obsws.ReqClient, source_name: str) -> set[str]:
    return {f["filterName"] for f in client.get_source_filter_list(source_name).filters}


def ensure_tape_effect(client: obsws.ReqClient, source_name: str, plugin_path: str = CHOWTAPE_VST2_PATH) -> None:
    if TAPE_FILTER_NAME in _existing_filter_names(client, source_name):
        return
    client.create_source_filter(source_name, TAPE_FILTER_NAME, FILTER_KIND, {"plugin_path": plugin_path})
