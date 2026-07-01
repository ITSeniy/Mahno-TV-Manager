"""VHS/NTSC-era analog video degradation via the obs-retro-effects plugin.

obs_retro_effects_filter is a single filter *kind* with an internal
"filter_type" int dropdown selecting which effect it renders (values below
are lifted from obs-retro-effects' source - obs-websocket has no way to
enumerate them, they're not exposed as a string enum). A combined
NTSC+VHS+scanlines look means stacking three separate instances of this
filter kind on the same scene, applied in signal-path order: NTSC
broadcast-encoding artifacts first, then VHS tape artifacts, then scanlines
last (closest to "the CRT you're watching it on").

Same hands-off-after-creation rule as overlays.py: each filter is only
created and tuned once. If someone nudges sliders in OBS afterward,
restarting the director must not reset them.
"""

import obsws_python as obsws

FILTER_KIND = "obs_retro_effects_filter"

RETRO_FILTER_NTSC = 7
RETRO_FILTER_VHS = 11
RETRO_FILTER_SCANLINES = 13

NTSC_FILTER_NAME = "retro_ntsc"
VHS_FILTER_NAME = "retro_vhs"
SCANLINES_FILTER_NAME = "retro_scanlines"

# (filter_name, settings) in the order they should sit in the filter chain.
FILTER_CHAIN: list[tuple[str, dict]] = [
    (
        NTSC_FILTER_NAME,
        {
            "filter_type": RETRO_FILTER_NTSC,
            "ntsc_tuning_offset": 1.0,
            "ntsc_luma_noise": 8.0,
            "ntsc_luma_band_strength": 60.0,
            "ntsc_chroma_bleed_size": 60.0,
            "ntsc_chroma_bleed_strength": 65.0,
            "ntsc_dot_crawl_amount": 40.0,
            "ntsc_comb_filter_strength": 100.0,
        },
    ),
    (
        VHS_FILTER_NAME,
        {
            "filter_type": RETRO_FILTER_VHS,
            "vhs_wrinkle_occurrence_prob": 4.0,
            "vhs_wrinkle_size": 3.0,
            "vhs_wrinkle_duration": 2.0,
            "vhs_jitter_min_size": 1.0,
            "vhs_jitter_max_size": 6.0,
            "vhs_pop_lines_amount": 6.0,
            "vhs_head_switch_primary_thickness": 10.0,
            "vhs_head_switch_primary_offset": 20.0,
        },
    ),
    (
        SCANLINES_FILTER_NAME,
        {
            "filter_type": RETRO_FILTER_SCANLINES,
            "scanlines_period": 24.0,
            "scanlines_intensity": 25.0,
            "scanlines_speed": 0.0,
        },
    ),
]


def _existing_filter_names(client: obsws.ReqClient, scene_name: str) -> set[str]:
    return {f["filterName"] for f in client.get_source_filter_list(scene_name).filters}


def ensure_vhs_effect(client: obsws.ReqClient, scene_name: str) -> None:
    existing = _existing_filter_names(client, scene_name)
    for index, (filter_name, settings) in enumerate(FILTER_CHAIN):
        if filter_name in existing:
            continue
        client.create_source_filter(scene_name, filter_name, FILTER_KIND, settings)
        client.set_source_filter_index(scene_name, filter_name, index)
