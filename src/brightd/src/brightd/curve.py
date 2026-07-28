"""Perceptual mapping between slider position and raw backlight values.

The raw register on a ``type=raw`` panel is a PWM duty count: roughly
proportional to emitted luminance, not to perceived brightness.  Mapping a
0-100 slider onto it linearly crushes the useful range into the bottom of the
travel -- on this laptop a comfortable 19200/192000 sits at 9.1% of a linear
slider, where one pixel of drag is a jarring jump.

CIE L* is the standard lightness scale: L* is approximately linear in
*perceived* lightness and ``Y(L*)`` converts back to relative luminance.
Driving the slider in L* puts that same comfortable setting at 36.2% of travel,
in the middle third where a slider has real resolution.  The CIE definition's
linear toe below L*=8 is what makes it preferable to a bare power curve, which
degenerates into sub-1 raw steps near zero.

This is an ergonomic choice, not verified physics: ``intel_backlight`` reports
``type=raw`` with ``scale=unknown``, meaning the kernel explicitly declines to
say whether the register is linear in luminance.

DDC/CI monitors get :class:`LinearCurve` instead -- VCP feature 0x10 is a
user-facing brightness control that panel firmware has already shaped, so
curving it a second time would double-apply the correction.

Nothing here imports GTK, so ``brightd-ctl`` maps percentages exactly the way
the daemon does and the mapping is unit-testable with no hardware.
"""

from __future__ import annotations

import abc

# CIE 15 break point.  The slope is the exact rational 24389/27, not its usual
# rounded form 903.3: with the exact value the linear toe meets the cubic
# segment precisely, because 8 / (24389/27) == 216/24389 == (24/116)**3.  The
# rounded constant leaves a ~3.6e-8 step at the knee, which is small but is a
# genuine discontinuity in a function that must round-trip cleanly.
_LSTAR_KNEE = 8.0
_LINEAR_SLOPE = 24389.0 / 27.0
_Y_KNEE = _LSTAR_KNEE / _LINEAR_SLOPE


def clamp(value: float, low: float, high: float) -> float:
    """Constrain ``value`` to ``[low, high]``."""
    return max(low, min(high, value))


def lstar_to_luminance(lstar: float) -> float:
    """Relative luminance ``Y`` in [0, 1] for lightness ``L*`` in [0, 100]."""
    lstar = clamp(lstar, 0.0, 100.0)
    if lstar <= _LSTAR_KNEE:
        return lstar / _LINEAR_SLOPE
    return ((lstar + 16.0) / 116.0) ** 3


def luminance_to_lstar(luminance: float) -> float:
    """Inverse of :func:`lstar_to_luminance`."""
    luminance = clamp(luminance, 0.0, 1.0)
    if luminance <= _Y_KNEE:
        return luminance * _LINEAR_SLOPE
    return 116.0 * (luminance ** (1.0 / 3.0)) - 16.0


class Curve(abc.ABC):
    """Bijection between slider percent [0, 100] and a fraction [0, 1]."""

    @abc.abstractmethod
    def to_fraction(self, percent: float) -> float:
        """Fraction of the raw span corresponding to a slider percentage."""

    @abc.abstractmethod
    def to_percent(self, fraction: float) -> float:
        """Slider percentage corresponding to a fraction of the raw span."""


class LStarCurve(Curve):
    """Perceptual curve for raw PWM backlights (see the module docstring)."""

    def to_fraction(self, percent: float) -> float:
        return lstar_to_luminance(percent)

    def to_percent(self, fraction: float) -> float:
        return luminance_to_lstar(fraction)


class LinearCurve(Curve):
    """Identity mapping, for controls that are already perceptually shaped."""

    def to_fraction(self, percent: float) -> float:
        return clamp(percent, 0.0, 100.0) / 100.0

    def to_percent(self, fraction: float) -> float:
        return clamp(fraction, 0.0, 1.0) * 100.0


def percent_to_raw(percent: float, min_raw: int, max_raw: int, curve: Curve) -> int:
    """Map a slider percentage onto a raw device value.

    ``min_raw`` is the dimmest *safe* value rather than the device's true zero,
    so 0% means "as dim as this display goes without blacking out".
    """
    if max_raw <= min_raw:
        return min_raw
    span = max_raw - min_raw
    raw = min_raw + span * curve.to_fraction(percent)
    return int(round(clamp(raw, float(min_raw), float(max_raw))))


def raw_to_percent(raw: int, min_raw: int, max_raw: int, curve: Curve) -> float:
    """Map a raw device value back onto a slider percentage."""
    if max_raw <= min_raw:
        return 0.0
    span = max_raw - min_raw
    fraction = (clamp(float(raw), float(min_raw), float(max_raw)) - min_raw) / span
    return clamp(curve.to_percent(fraction), 0.0, 100.0)
