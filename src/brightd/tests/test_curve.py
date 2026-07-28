"""The percent <-> raw mapping, which every other component depends on.

A non-idempotent round trip is the fuel for the slider echo runaway: the UI
writes a percent, reads a raw value back, converts it to a slightly different
percent, and walks the value away from where the user put it.  So round-trip
stability is tested as a property, not on a couple of examples.
"""

from __future__ import annotations

import pytest

from brightd.curve import (
    LinearCurve,
    LStarCurve,
    clamp,
    luminance_to_lstar,
    lstar_to_luminance,
    percent_to_raw,
    raw_to_percent,
)

# (min_raw, max_raw) pairs: the real panel, a DDC monitor, and a coarse one.
RANGES = [(1920, 192000), (0, 100), (1, 255), (0, 1000)]
CURVES = [LStarCurve(), LinearCurve()]


def test_lstar_curve_is_continuous_at_the_knee() -> None:
    """The linear toe must land exactly where the cubic segment starts.

    Only true with the exact slope 24389/27, for which 8/(24389/27) and
    (24/116)**3 are the same rational number, 216/24389.  The commonly quoted
    rounding 903.3 leaves a ~3.6e-8 step here.
    """
    toe_at_knee = lstar_to_luminance(8.0)
    cubic_at_knee = ((8.0 + 16.0) / 116.0) ** 3
    assert toe_at_knee == pytest.approx(cubic_at_knee, rel=1e-12)

    # And no step across the boundary, allowing only for the curve's own slope
    # over the sampling gap (dY/dL* = 27/24389 there).
    epsilon = 1e-9
    span = 4.0 * epsilon * 27.0 / 24389.0
    assert lstar_to_luminance(8.0 - epsilon) == pytest.approx(
        lstar_to_luminance(8.0 + epsilon), abs=span
    )


@pytest.mark.parametrize("lstar", [0.0, 1.0, 8.0, 25.0, 50.0, 99.0, 100.0])
def test_luminance_round_trip(lstar: float) -> None:
    assert luminance_to_lstar(lstar_to_luminance(lstar)) == pytest.approx(lstar, abs=1e-6)


def quantisation_tolerance(curve: LStarCurve | LinearCurve, min_raw: int, max_raw: int) -> float:
    """Widest percentage gap a single raw step can span, for this curve.

    A device with only 100 raw steps physically cannot represent every
    percentage, and under a perceptual curve the coarsest region is the bottom
    of the range -- one raw step there is worth several L* points.  Asserting a
    flat tolerance would therefore be testing arithmetic rather than the curve,
    so the bound is derived from the device's own resolution.
    """
    steps = max_raw - min_raw
    if steps <= 0:
        return 0.0
    return max(0.5, curve.to_percent(1.0 / steps) - curve.to_percent(0.0))


@pytest.mark.parametrize("curve", CURVES, ids=lambda c: type(c).__name__)
@pytest.mark.parametrize("bounds", RANGES, ids=repr)
def test_percent_round_trip_is_stable(curve: LStarCurve | LinearCurve, bounds: tuple[int, int]) -> None:
    """Converting to raw and back must not drift the value."""
    min_raw, max_raw = bounds
    tolerance = quantisation_tolerance(curve, min_raw, max_raw)

    for tenth in range(0, 1001):
        percent = tenth / 10.0
        raw = percent_to_raw(percent, min_raw, max_raw, curve)
        back = raw_to_percent(raw, min_raw, max_raw, curve)
        assert back == pytest.approx(percent, abs=tolerance), f"{percent} -> {raw} -> {back}"


@pytest.mark.parametrize("curve", CURVES, ids=lambda c: type(c).__name__)
def test_percent_to_raw_is_monotonic(curve: LStarCurve | LinearCurve) -> None:
    values = [percent_to_raw(p / 2.0, 1920, 192000, curve) for p in range(201)]
    assert values == sorted(values)


def test_zero_percent_is_the_floor_not_black() -> None:
    """0% must land on the safe minimum, never on a black screen."""
    assert percent_to_raw(0.0, 1920, 192000, LStarCurve()) == 1920
    assert percent_to_raw(-50.0, 1920, 192000, LStarCurve()) == 1920


def test_hundred_percent_is_the_maximum() -> None:
    assert percent_to_raw(100.0, 1920, 192000, LStarCurve()) == 192000
    assert percent_to_raw(1e6, 1920, 192000, LStarCurve()) == 192000


def test_lstar_puts_a_dim_setting_mid_travel() -> None:
    """The whole point of the curve: 10% of max must not sit at 9% of travel.

    19200/192000 is the level this laptop is actually used at.
    """
    percent = raw_to_percent(19200, 1920, 192000, LStarCurve())
    assert 30.0 < percent < 42.0
    linear = raw_to_percent(19200, 1920, 192000, LinearCurve())
    assert linear < 10.0


def test_degenerate_range_does_not_divide_by_zero() -> None:
    assert percent_to_raw(50.0, 100, 100, LStarCurve()) == 100
    assert raw_to_percent(100, 100, 100, LStarCurve()) == 0.0


def test_clamp() -> None:
    assert clamp(5.0, 0.0, 1.0) == 1.0
    assert clamp(-5.0, 0.0, 1.0) == 0.0
    assert clamp(0.5, 0.0, 1.0) == 0.5
