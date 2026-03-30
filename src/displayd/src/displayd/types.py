"""Core data types for displayd."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class EventKind(Enum):
    DRM_CHANGE = auto()
    DRM_ADD = auto()
    DRM_REMOVE = auto()
    LID_OPEN = auto()
    LID_CLOSE = auto()
    RESUME = auto()
    SESSION_UNLOCK = auto()
    SESSION_NEW = auto()
    SESSION_ACTIVE = auto()
    STARTUP = auto()


@dataclass(frozen=True)
class DisplayEvent:
    kind: EventKind
    detail: str = ""
    timestamp: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class MonitorIdentity:
    """Stable monitor identity derived from EDID data."""

    manufacturer: str
    model: str
    serial: str

    @property
    def stable_id(self) -> str:
        return f"{self.manufacturer}/{self.model}/{self.serial}"

    def matches(self, other: MonitorIdentity) -> bool:
        """Fuzzy match: manufacturer+model must agree; serial only if both present."""
        if self.manufacturer != other.manufacturer:
            return False
        if self.model != other.model:
            return False
        if self.serial and other.serial:
            return self.serial == other.serial
        return True


UNKNOWN_IDENTITY = MonitorIdentity("???", "???", "")


@dataclass(frozen=True)
class ConnectedOutput:
    """A physically connected display output with its current state."""

    connector: str
    identity: MonitorIdentity
    modes: tuple[str, ...] = ()
    current_mode: Optional[str] = None
    current_position: tuple[int, int] = (0, 0)
    current_rotation: str = "normal"
    is_primary: bool = False
    edid_raw: bytes = b""


@dataclass(frozen=True)
class OutputConfig:
    """Desired configuration for a single output in a profile."""

    identity: MonitorIdentity
    enabled: bool = True
    mode: Optional[str] = None
    position: tuple[int, int] = (0, 0)
    rotation: str = "normal"
    primary: bool = False
    scale: float = 1.0


@dataclass(frozen=True)
class Topology:
    """Snapshot of all connected displays plus lid state."""

    outputs: tuple[ConnectedOutput, ...]
    lid_closed: bool = False

    @property
    def identity_hash(self) -> str:
        """Hash based purely on monitor identities -- stable across connector renames."""
        identities = sorted(o.identity.stable_id for o in self.outputs)
        blob = json.dumps(
            {"monitors": identities, "lid_closed": self.lid_closed}, sort_keys=True
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @property
    def full_state_hash(self) -> str:
        """Hash that also includes modes, positions, rotation -- for change detection."""
        items = sorted(
            (
                o.connector,
                o.identity.stable_id,
                o.current_mode or "",
                o.current_position,
                o.current_rotation,
            )
            for o in self.outputs
        )
        blob = json.dumps(
            {"outputs": items, "lid_closed": self.lid_closed},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def output_by_identity(self, identity: MonitorIdentity) -> Optional[ConnectedOutput]:
        for o in self.outputs:
            if o.identity.matches(identity):
                return o
        return None

    @property
    def monitor_count(self) -> int:
        return len(self.outputs)


@dataclass
class Profile:
    """A saved display profile that maps to a topology."""

    name: str
    topology_hash: str
    outputs: tuple[OutputConfig, ...]
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "topology_hash": self.topology_hash,
            "priority": self.priority,
            "outputs": [
                {
                    "identity": o.identity.stable_id,
                    "enabled": o.enabled,
                    "mode": o.mode,
                    "position": list(o.position),
                    "rotation": o.rotation,
                    "primary": o.primary,
                    "scale": o.scale,
                }
                for o in self.outputs
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        outputs: list[OutputConfig] = []
        for entry in data.get("outputs", []):
            parts = entry["identity"].split("/", 2)
            identity = MonitorIdentity(
                manufacturer=parts[0] if len(parts) > 0 else "???",
                model=parts[1] if len(parts) > 1 else "???",
                serial=parts[2] if len(parts) > 2 else "",
            )
            outputs.append(
                OutputConfig(
                    identity=identity,
                    enabled=entry.get("enabled", True),
                    mode=entry.get("mode"),
                    position=tuple(entry.get("position", [0, 0])),
                    rotation=entry.get("rotation", "normal"),
                    primary=entry.get("primary", False),
                    scale=entry.get("scale", 1.0),
                )
            )
        return cls(
            name=data["name"],
            topology_hash=data["topology_hash"],
            outputs=tuple(outputs),
            priority=data.get("priority", 0),
        )


@dataclass
class ReconciliationPlan:
    """Describes what must change to reach a desired display profile."""

    profile: Profile
    changes: list[tuple[str, OutputConfig]]
    is_noop: bool = False
