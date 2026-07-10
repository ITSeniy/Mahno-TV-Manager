"""The cloth loop's actual rendering needs a browser + ffmpeg, so it's exercised
on scratch, not here. These guard the two things a typo would silently break:
the deterministic single-frame hook and the periodic-loop shader wiring."""

from director import cloth_bg


def test_html_exposes_deterministic_single_frame_hook():
    # render_cloth_loop drives capture through window.setLoopT(t); without it every
    # frame would be blank and the loop would never seam.
    assert "window.setLoopT" in cloth_bg.CLOTH_HTML
    assert "preserveDrawingBuffer" in cloth_bg.CLOTH_HTML  # canvas must survive until screenshot


def test_shader_is_loop_periodic_not_wall_clock():
    html = cloth_bg.CLOTH_HTML
    # Driven by a normalized loop phase, not free-running u_time.
    assert "u_loopT" in html and "u_time" not in html
    # Rightward drift closes over the loop: NX even, warp orbits a circle.
    assert "NX * A" in html or "NX*A" in html
    assert "cos(A), sin(A)" in html or "cos(A),sin(A)" in html


def test_dimensions_are_ntsc_plate():
    assert (cloth_bg.CLOTH_WIDTH, cloth_bg.CLOTH_HEIGHT) == (720, 480)
