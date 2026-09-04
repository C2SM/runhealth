"""The palette makes accessibility claims; check them rather than trust them."""

import pytest

from runhealth import style


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)))
    return (lb + 0.05) / (la + 0.05)


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_body_text_is_readable(dark):
    t = style.tokens(dark)
    for ground in ("bg", "panel", "panel-2"):
        assert contrast(t["ink"], t[ground]) >= 4.5, ground


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_secondary_text_clears_the_large_text_threshold(dark):
    t = style.tokens(dark)
    # Captions, axis labels and tick labels are all drawn in these.
    for name in ("muted", "tick"):
        assert contrast(t[name], t["panel"]) >= 3.0, name


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_series_and_verdict_colours_stand_out_as_graphics(dark):
    t = style.tokens(dark)
    names = [f"s{i}" for i in range(len(style.SERIES_LIGHT))] + ["ok", "info", "warn", "fail"]
    for name in names:
        assert contrast(t[name], t["panel"]) >= 3.0, f"{name} on {'dark' if dark else 'light'}"


def test_white_labels_inside_a_phase_bar_stay_legible():
    # One phase ramp serves both themes precisely so this holds either way.
    for i, color in enumerate(style.PHASES):
        assert contrast("#ffffff", color) >= 4.5, f"phase {i} ({color})"


def test_every_class_the_figures_use_has_a_literal_fallback():
    # Without one, the PDF renders the figure in black.
    for classes in ("p0 fill mark", "s3 stroke", "lv-fail fill", "s1 area", "grid", "in-bar"):
        assert style.svg_attributes(classes), classes
