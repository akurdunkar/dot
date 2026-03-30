"""Profile matching, reconciliation planning, and profile persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .types import (
    ConnectedOutput,
    MonitorIdentity,
    OutputConfig,
    Profile,
    ReconciliationPlan,
    Topology,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile storage
# ---------------------------------------------------------------------------


def load_profiles(profile_dir: Path) -> list[Profile]:
    profiles: list[Profile] = []
    if not profile_dir.is_dir():
        return profiles
    for path in sorted(profile_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            profiles.append(Profile.from_dict(data))
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            log.warning("Skipping invalid profile %s: %s", path, exc)
    return profiles


def save_profile(profile: Profile, profile_dir: Path) -> Path:
    profile_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in profile.name)
    path = profile_dir / f"{safe}.json"
    path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n")
    log.info("Saved profile %r -> %s", profile.name, path)
    return path


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def match_profile(
    topology: Topology, profiles: list[Profile]
) -> Optional[Profile]:
    topo_hash = topology.identity_hash
    candidates = [p for p in profiles if p.topology_hash == topo_hash]
    if not candidates:
        log.info("No profile matches topology %s", topo_hash)
        return None
    best = max(candidates, key=lambda p: p.priority)
    log.info(
        "Matched profile %r (priority=%d) for topology %s",
        best.name,
        best.priority,
        topo_hash,
    )
    return best


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def plan_reconciliation(
    topology: Topology,
    profile: Profile,
) -> ReconciliationPlan:
    changes: list[tuple[str, OutputConfig]] = []

    for desired in profile.outputs:
        output = topology.output_by_identity(desired.identity)
        if output is None:
            log.warning(
                "Profile output %s not present in topology",
                desired.identity.stable_id,
            )
            continue

        if not desired.enabled:
            needs_change = output.current_mode is not None
        else:
            needs_change = (
                output.current_mode != desired.mode
                or output.current_position != desired.position
                or output.current_rotation != desired.rotation
                or output.is_primary != desired.primary
            )
        if needs_change:
            changes.append((output.connector, desired))

    is_noop = len(changes) == 0
    if is_noop:
        log.info("Reconciliation: no-op")
    else:
        log.info("Reconciliation: %d output(s) need changes", len(changes))

    return ReconciliationPlan(profile=profile, changes=changes, is_noop=is_noop)


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------


def snapshot_to_profile(
    name: str,
    topology: Topology,
    priority: int = 0,
) -> Profile:
    """Capture the current topology as a saveable Profile."""
    outputs = tuple(
        OutputConfig(
            identity=o.identity,
            enabled=o.current_mode is not None,
            mode=o.current_mode,
            position=o.current_position,
            rotation=o.current_rotation,
            primary=o.is_primary,
        )
        for o in topology.outputs
    )
    return Profile(
        name=name,
        topology_hash=topology.identity_hash,
        outputs=outputs,
        priority=priority,
    )
