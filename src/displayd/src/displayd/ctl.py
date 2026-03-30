"""displayd-ctl -- profile and topology management CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .backends import detect_backend
from .log import setup_logging
from .policy import load_profiles, match_profile, plan_reconciliation, save_profile, snapshot_to_profile

DEFAULT_PROFILE_DIR = Path(
    os.environ.get(
        "DISPLAYD_PROFILE_DIR",
        os.path.expanduser("~/.config/displayd/profiles"),
    )
)


async def _cmd_show(args: argparse.Namespace) -> None:
    backend = detect_backend()
    topo = await backend.get_topology()
    print(f"Topology identity hash: {topo.identity_hash}")
    print(f"Full state hash:        {topo.full_state_hash}")
    print(f"Connected outputs:      {topo.monitor_count}")
    print()
    for o in topo.outputs:
        flags = []
        if o.is_primary:
            flags.append("primary")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {o.connector}{flag_str}")
        print(f"    Identity: {o.identity.stable_id}")
        print(f"    Mode:     {o.current_mode or '(none)'}")
        print(f"    Position: {o.current_position[0]}x{o.current_position[1]}")
        print(f"    Rotation: {o.current_rotation}")
        if o.modes:
            print(f"    Modes:    {', '.join(o.modes[:6])}", end="")
            if len(o.modes) > 6:
                print(f" (+{len(o.modes) - 6} more)", end="")
            print()
        print()


async def _cmd_save(args: argparse.Namespace) -> None:
    backend = detect_backend()
    topo = await backend.get_topology()
    if topo.monitor_count == 0:
        sys.exit("No connected outputs detected")

    profile = snapshot_to_profile(args.name, topo, priority=args.priority)
    path = save_profile(profile, args.profile_dir)
    print(f"Saved profile '{args.name}' ({topo.monitor_count} output(s))")
    print(f"  Topology hash: {topo.identity_hash}")
    print(f"  File:          {path}")


def _cmd_list(args: argparse.Namespace) -> None:
    profiles = load_profiles(args.profile_dir)
    if not profiles:
        print(f"No profiles in {args.profile_dir}")
        return
    for p in profiles:
        print(f"  {p.name}")
        print(f"    Hash:     {p.topology_hash}")
        print(f"    Priority: {p.priority}")
        print(f"    Outputs:  {len(p.outputs)}")
        for o in p.outputs:
            mode = o.mode or "(any)"
            pri = " [primary]" if o.primary else ""
            state = mode if o.enabled else "(disabled)"
            print(f"      {o.identity.stable_id}  {state}  {o.position[0]}x{o.position[1]}{pri}")
        print()


async def _cmd_status(args: argparse.Namespace) -> None:
    backend = detect_backend()
    topo = await backend.get_topology()
    profiles = load_profiles(args.profile_dir)

    print(f"Topology: {topo.identity_hash}  ({topo.monitor_count} output(s))")
    for o in topo.outputs:
        pri = " [primary]" if o.is_primary else ""
        mode = o.current_mode or "(off)"
        print(f"  {o.connector}: {o.identity.stable_id}  {mode}{pri}")

    print()
    prof = match_profile(topo, profiles)
    if prof is None:
        print("Matched profile: (none)")
        return

    print(f"Matched profile: {prof.name}  (priority={prof.priority})")
    plan = plan_reconciliation(topo, prof)
    if plan.is_noop:
        print("Status: in sync")
    else:
        print(f"Status: {len(plan.changes)} change(s) needed")
        for connector, cfg in plan.changes:
            if not cfg.enabled:
                print(f"  {connector}: turn off")
            else:
                parts = []
                if cfg.mode:
                    parts.append(cfg.mode)
                parts.append(f"pos {cfg.position[0]}x{cfg.position[1]}")
                if cfg.primary:
                    parts.append("primary")
                if cfg.rotation != "normal":
                    parts.append(f"rotate {cfg.rotation}")
                print(f"  {connector}: {', '.join(parts)}")


def _cmd_delete(args: argparse.Namespace) -> None:
    profiles = load_profiles(args.profile_dir)
    match = [p for p in profiles if p.name == args.name]
    if not match:
        sys.exit(f"No profile named '{args.name}'")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.name)
    path = args.profile_dir / f"{safe}.json"
    if path.exists():
        path.unlink()
        print(f"Deleted profile '{args.name}'")
    else:
        sys.exit(f"Profile file not found at {path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="displayd-ctl",
        description="Manage display profiles and inspect topology",
    )
    ap.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Profile directory (default: %(default)s)",
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show matched profile and sync state")
    sub.add_parser("show", help="Show current display topology")

    sp_save = sub.add_parser("save", help="Save current layout as a profile")
    sp_save.add_argument("name", help="Profile name")
    sp_save.add_argument(
        "--priority", type=int, default=0,
        help="Profile priority (higher wins, default: 0)",
    )

    sub.add_parser("list", help="List saved profiles")

    sp_del = sub.add_parser("delete", help="Delete a saved profile")
    sp_del.add_argument("name", help="Profile name to delete")

    args = ap.parse_args()

    if args.verbose:
        setup_logging("displayd", level=10)

    if args.command == "status":
        asyncio.run(_cmd_status(args))
    elif args.command == "show":
        asyncio.run(_cmd_show(args))
    elif args.command == "save":
        asyncio.run(_cmd_save(args))
    elif args.command == "list":
        _cmd_list(args)
    elif args.command == "delete":
        _cmd_delete(args)


if __name__ == "__main__":
    main()
