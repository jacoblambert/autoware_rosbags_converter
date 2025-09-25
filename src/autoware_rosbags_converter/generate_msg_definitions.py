"""CLI to generate Python message definitions from ROS msg sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

from autoware_rosbags_converter.msg_definition_generator import MsgDefinitionGenerator, build_manifest
from autoware_rosbags_converter.typestore import validate_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("msg_definitions_src"),
        help="Directory containing ROS msg package sources.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("src/autoware_rosbags_converter/msg_definitions"),
        help="Directory to write copied ROS msg files.",
    )
    parser.add_argument(
        "--packages",
        type=str,
        nargs="*",
        help="Optional list of package directories to process (relative to source root).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated messages by loading them into a rosbags typestore.",
    )
    args = parser.parse_args()

    source_root: Path = args.source_root.resolve()
    output_root: Path = args.output_root.resolve()
    manifest_path: Path = output_root / "manifest.json"

    entries = _discover_msg_directories(source_root, args.packages)
    if not entries:
        raise SystemExit("No msg directories found to generate.")

    generator = MsgDefinitionGenerator(output_root=output_root)
    artifacts = generator.generate_many(entries)

    manifest = build_manifest(artifacts, output_root=output_root)

    if manifest_path.parent:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    if args.validate:
        try:
            validate_manifest(manifest_path, base_path=output_root)
        except ImportError as exc:  # rosbags missing
            raise SystemExit(
                "Validation requires the 'rosbags' package. Install extras with 'uv pip install .[dev]'"
            ) from exc
        except Exception as exc:  # pragma: no cover - surfaces to CLI
            raise SystemExit(str(exc)) from exc


def entrypoint() -> None:  # pragma: no cover - thin wrapper for UV console script
    try:
        main()
    except SystemExit as exc:
        raise exc
    except Exception as exc:  # pragma: no cover
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _discover_msg_directories(source_root: Path, filters: List[str] | None) -> List[Tuple[str, Path, Path]]:
    search_roots: Iterable[Path]
    if filters:
        search_roots = [source_root.joinpath(item).resolve() for item in filters]
    else:
        search_roots = [source_root]

    seen: set[Tuple[str, Path]] = set()
    results: List[Tuple[str, Path, Path]] = []
    for root in search_roots:
        if not root.exists():
            continue
        for msg_dir in sorted(root.rglob("msg")):
            if not msg_dir.is_dir():
                continue
            package_root = _find_package_root(msg_dir)
            if not package_root:
                continue
            package_name = _read_package_name(package_root / "package.xml")
            if not package_name:
                continue
            entry_key = (package_name, msg_dir.resolve())
            if entry_key in seen:
                continue
            seen.add(entry_key)
            results.append((package_name, package_root.resolve(), msg_dir.resolve()))
    results.sort(key=lambda item: (item[0], str(item[2])))
    return results


def _find_package_root(msg_dir: Path) -> Path | None:
    current = msg_dir.parent
    while True:
        package_xml = current / "package.xml"
        if package_xml.exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _read_package_name(package_xml_path: Path) -> str | None:
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(package_xml_path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    for element in root.iter():
        tag = element.tag.split('}', 1)[-1]
        if tag == "name" and element.text:
            return element.text.strip()
    return None


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
