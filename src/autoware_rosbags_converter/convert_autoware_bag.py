"""Inspect an Autoware rosbag and report custom message coverage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Tuple

from autoware_rosbags_converter.typestore import install_in_typestore

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bag", type=Path, help="Path to the rosbag2 directory to inspect.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("src/autoware_rosbags_converter/manifest.json"),
        help="Manifest produced by generate_msg_definitions.py.",
    )
    return parser.parse_args()

def inspect_bag(
    bag_path: Path,
    manifest_path: Path,
) -> Tuple[Iterable[Tuple[str, str]], Iterable[str]]:
    """Load a rosbag2 file and compare connection types to our typestore."""

    try:
        from rosbags.rosbag2 import Reader
        from rosbags.typesys import Stores, get_typestore
    except ImportError as exc:  # pragma: no cover - dependency optional
        raise ImportError(
            "rosbags is required to inspect Autoware bags. Install it via 'uv pip install .[dev]'"
        ) from exc

    bag_path = bag_path.resolve()
    manifest_path = manifest_path.resolve()
    if not bag_path.exists():  # pragma: no cover - defensive guard
        raise FileNotFoundError(f"Rosbag path not found: {bag_path}")
    if not manifest_path.exists():  # pragma: no cover - defensive guard
        raise FileNotFoundError(f"Manifest path not found: {manifest_path}")
    
    typestore = get_typestore(Stores.ROS2_HUMBLE)
    install_in_typestore(manifest_path, base_path=manifest_path.parent, typestore=typestore)

    connections: list[Tuple[str, str]] = []
    missing: set[str] = set()

    with Reader(bag_path) as reader:
        for connection in reader.connections:
            topic = connection.topic
            msgtype = connection.msgtype
            connections.append((topic, msgtype))
            if msgtype not in typestore.types:
                missing.add(msgtype)

    return connections, sorted(missing)


def main() -> None:  # pragma: no cover - CLI entry point
    args = parse_args()

    try:
        connections, missing = inspect_bag(args.bag, args.manifest)
    except Exception as exc:  # pragma: no cover - user feedback
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Loaded {len(connections)} connections from {args.bag}.")
    if missing:
        print(f"Missing {len(missing)} message definitions:")
        for name in missing:
            print(f"  - {name}")
    else:
        print("All connection types are registered in the typestore.")


if __name__ == "__main__":  # pragma: no cover
    main()
