"""The interface every brightness backend implements.

Backends deal only in percentages.  The raw-value and curve details are private
to each backend because they differ fundamentally: a kernel backlight is a
192000-step linear PWM register that needs a perceptual curve, while a DDC
monitor is a 0-100 control that firmware has already shaped.

The throttle attributes are declared here rather than inside the writer so the
writer stays generic.  They are what lets a sysfs write go out on every frame
of a drag while a DDC write -- three orders of magnitude slower, and capable of
wedging a monitor if hammered -- is coalesced.
"""

from __future__ import annotations

import abc

from ..types import DisplayInfo


class Backlight(abc.ABC):
    """A single controllable display brightness."""

    min_period: float = 0.0
    """Minimum seconds between consecutive writes.  0 writes every update."""

    debounce: float = 0.0
    """Seconds to wait before the first write of a gesture, to collapse flicks."""

    @property
    @abc.abstractmethod
    def info(self) -> DisplayInfo:
        """Identity and human-facing label for this display."""

    @abc.abstractmethod
    def read_percent(self) -> float:
        """Current brightness as a percentage in [0, 100]."""

    @abc.abstractmethod
    def write_percent(self, percent: float) -> None:
        """Set brightness from a percentage in [0, 100]."""

    def close(self) -> None:
        """Release any held file descriptors or subprocesses."""
