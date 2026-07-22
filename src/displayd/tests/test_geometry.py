"""Tests for the pure layout-editor geometry helpers."""

from __future__ import annotations

import pytest

from displayd.ui.geometry import (
    MAX_SCALE,
    bounding_box,
    compute_scale,
    effective_size,
    normalize_positions,
    parse_mode,
    snap_position,
)


# ---------------------------------------------------------------------------
# parse_mode / effective_size
# ---------------------------------------------------------------------------


class TestParseMode:
    def test_basic(self):
        assert parse_mode("3440x1440") == (3440, 1440)
        assert parse_mode("1920x1080") == (1920, 1080)

    def test_uppercase_separator(self):
        assert parse_mode("1920X1080") == (1920, 1080)

    def test_surrounding_whitespace(self):
        assert parse_mode("  2560x1080") == (2560, 1080)

    def test_trailing_refresh_decoration(self):
        assert parse_mode("1920x1080@60") == (1920, 1080)
        assert parse_mode("1920x1080i") == (1920, 1080)

    @pytest.mark.parametrize(
        "junk", ["", "garbage", "x1080", "1920x", "1920", "axb", "x"]
    )
    def test_junk_raises(self, junk: str):
        with pytest.raises(ValueError):
            parse_mode(junk)


class TestEffectiveSize:
    def test_normal_keeps_dimensions(self):
        assert effective_size("3440x1440", "normal") == (3440, 1440)

    def test_inverted_keeps_dimensions(self):
        assert effective_size("3440x1440", "inverted") == (3440, 1440)

    def test_left_swaps(self):
        assert effective_size("3440x1440", "left") == (1440, 3440)

    def test_right_swaps(self):
        assert effective_size("3440x1440", "right") == (1440, 3440)

    def test_junk_mode_raises(self):
        with pytest.raises(ValueError):
            effective_size("junk", "left")


# ---------------------------------------------------------------------------
# bounding_box
# ---------------------------------------------------------------------------


class TestBoundingBox:
    def test_empty(self):
        assert bounding_box([]) == (0, 0, 0, 0)

    def test_single_rect(self):
        assert bounding_box([(100, 200, 300, 400)]) == (100, 200, 400, 600)

    def test_multiple_rects(self):
        rects = [(0, 0, 1920, 1080), (1920, -200, 3440, 1440)]
        assert bounding_box(rects) == (0, -200, 5360, 1240)

    def test_negative_coordinates(self):
        rects = [(-500, -300, 100, 100), (0, 0, 50, 50)]
        assert bounding_box(rects) == (-500, -300, 50, 50)


# ---------------------------------------------------------------------------
# compute_scale
# ---------------------------------------------------------------------------


class TestComputeScale:
    def test_scale_capped_for_small_bounds(self):
        scale, _, _ = compute_scale((0, 0, 100, 100), 900, 600)
        assert scale == MAX_SCALE

    def test_large_bounds_fit_within_margins(self):
        bounds = (0, 0, 10000, 5000)
        widget_w, widget_h, margin = 920, 600, 24
        scale, _, _ = compute_scale(bounds, widget_w, widget_h, margin)
        assert scale == pytest.approx((widget_w - 2 * margin) / 10000)
        assert 10000 * scale <= widget_w - 2 * margin
        assert 5000 * scale <= widget_h - 2 * margin

    def test_centering(self):
        bounds = (100, -200, 5100, 2800)
        widget_w, widget_h = 920, 600
        scale, ox, oy = compute_scale(bounds, widget_w, widget_h)
        cx = (bounds[0] + bounds[2]) / 2 * scale + ox
        cy = (bounds[1] + bounds[3]) / 2 * scale + oy
        assert cx == pytest.approx(widget_w / 2)
        assert cy == pytest.approx(widget_h / 2)

    def test_min_corner_lands_inside_margin(self):
        bounds = (0, 0, 10000, 5000)
        scale, ox, oy = compute_scale(bounds, 920, 600, margin=24)
        assert 0 * scale + ox >= 24 - 1e-9
        assert 10000 * scale + ox <= 920 - 24 + 1e-9

    def test_degenerate_bounds(self):
        scale, ox, oy = compute_scale((0, 0, 0, 0), 800, 600)
        assert scale == MAX_SCALE
        assert ox == pytest.approx(400)
        assert oy == pytest.approx(300)

    def test_tiny_widget_keeps_scale_positive(self):
        scale, _, _ = compute_scale((0, 0, 1920, 1080), 10, 10)
        assert scale > 0


# ---------------------------------------------------------------------------
# snap_position
# ---------------------------------------------------------------------------

OTHER = (1000, 3000, 1000, 500)  # x, y, w, h -> right edge 2000, bottom 3500


class TestSnapPosition:
    def test_left_to_right_adjacency(self):
        x, y = snap_position(2010, 3000, 800, 500, [OTHER], 32)
        assert x == 2000

    def test_right_to_left_adjacency(self):
        x, y = snap_position(215, 3000, 800, 500, [OTHER], 32)
        assert x == 200  # ox - w = 1000 - 800

    def test_left_to_left_alignment(self):
        x, y = snap_position(1015, 3000, 800, 500, [OTHER], 32)
        assert x == 1000

    def test_right_to_right_alignment(self):
        x, y = snap_position(1190, 3000, 800, 500, [OTHER], 32)
        assert x == 1200  # ox + ow - w = 2000 - 800

    def test_top_to_bottom_adjacency(self):
        x, y = snap_position(1000, 3520, 800, 500, [OTHER], 32)
        assert y == 3500

    def test_bottom_to_top_adjacency(self):
        x, y = snap_position(1000, 2510, 800, 500, [OTHER], 32)
        assert y == 2500  # oy - h = 3000 - 500

    def test_top_to_top_alignment(self):
        x, y = snap_position(1000, 3015, 800, 500, [OTHER], 32)
        assert y == 3000

    def test_bottom_to_bottom_alignment(self):
        x, y = snap_position(1000, 3110, 800, 400, [OTHER], 32)
        assert y == 3100  # oy + oh - h = 3500 - 400

    def test_origin_snap(self):
        assert snap_position(20, -15, 800, 500, [], 32) == (0, 0)

    def test_origin_snap_with_others_far_away(self):
        x, y = snap_position(20, -15, 800, 500, [(9000, 9000, 100, 100)], 32)
        assert (x, y) == (0, 0)

    def test_threshold_rejection(self):
        x, y = snap_position(2050, 3060, 800, 500, [OTHER], 32)
        assert (x, y) == (2050, 3060)

    def test_axes_independent(self):
        x, y = snap_position(2010, 3200, 800, 500, [OTHER], 32)
        assert x == 2000
        assert y == 3200

    def test_nearest_candidate_wins(self):
        a = (0, 0, 1000, 500)  # right edge 1000
        b = (1010, 5000, 500, 500)  # left edge 1010
        x, y = snap_position(1008, 0, 400, 500, [a, b], 32)
        assert x == 1010

    def test_no_others_no_origin_within_threshold(self):
        assert snap_position(500, 700, 800, 500, [], 32) == (500, 700)

    def test_exact_threshold_snaps(self):
        x, _ = snap_position(2032, 3000, 800, 500, [OTHER], 32)
        assert x == 2000


# ---------------------------------------------------------------------------
# normalize_positions
# ---------------------------------------------------------------------------


class TestNormalizePositions:
    def test_shifts_enabled_min_to_zero(self):
        positions = {"a": (100, 50), "b": (1920, 50)}
        sizes = {"a": (1920, 1080), "b": (3440, 1440)}
        enabled = {"a": True, "b": True}
        out = normalize_positions(positions, sizes, enabled)
        assert out == {"a": (0, 0), "b": (1820, 0)}

    def test_disabled_shifted_by_same_delta(self):
        positions = {"a": (100, 50), "b": (1920, 50), "c": (5000, 600)}
        sizes = {n: (1920, 1080) for n in positions}
        enabled = {"a": True, "b": True, "c": False}
        out = normalize_positions(positions, sizes, enabled)
        assert out["c"] == (4900, 550)

    def test_disabled_does_not_affect_delta(self):
        positions = {"a": (0, 0), "b": (1920, 0), "c": (-500, -500)}
        sizes = {n: (1920, 1080) for n in positions}
        enabled = {"a": True, "b": True, "c": False}
        out = normalize_positions(positions, sizes, enabled)
        assert out["a"] == (0, 0)
        assert out["b"] == (1920, 0)
        assert out["c"] == (-500, -500)

    def test_negative_enabled_positions(self):
        positions = {"a": (-1920, -200), "b": (0, 0)}
        sizes = {"a": (1920, 1080), "b": (1920, 1080)}
        enabled = {"a": True, "b": True}
        out = normalize_positions(positions, sizes, enabled)
        assert out == {"a": (0, 0), "b": (1920, 200)}

    def test_mins_taken_per_axis_across_outputs(self):
        positions = {"a": (100, 900), "b": (700, 300)}
        sizes = {"a": (1920, 1080), "b": (1920, 1080)}
        enabled = {"a": True, "b": True}
        out = normalize_positions(positions, sizes, enabled)
        assert out == {"a": (0, 600), "b": (600, 0)}

    def test_nothing_enabled_returns_unchanged(self):
        positions = {"a": (100, 50), "b": (1920, 50)}
        sizes = {"a": (1920, 1080), "b": (1920, 1080)}
        enabled = {"a": False, "b": False}
        assert normalize_positions(positions, sizes, enabled) == positions

    def test_enabled_name_missing_from_positions_ignored(self):
        positions = {"a": (100, 50)}
        sizes = {"a": (1920, 1080)}
        enabled = {"a": True, "ghost": True}
        assert normalize_positions(positions, sizes, enabled) == {"a": (0, 0)}

    def test_result_is_new_dict(self):
        positions = {"a": (0, 0)}
        out = normalize_positions(positions, {"a": (10, 10)}, {"a": True})
        assert out is not positions
