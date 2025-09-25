"""Helpers to register generated ROS .msg files with rosbags typestores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Set, Tuple
from rich import print

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rosbags.typesys.store import Typestore
else:  # pragma: no cover - fallback for runtime without rosbags
    Typestore = Any

def load_manifest(manifest_path: Path) -> Dict[str, str]:
    """Load the manifest mapping ROS type names to relative .msg paths."""

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def collect_messages(
    manifest_path: Path,
    *,
    base_path: Path | None = None,
) -> Dict[str, str]:
    """Return raw message definitions keyed by ROS type."""

    manifest = load_manifest(manifest_path)
    root = (base_path or manifest_path.parent).resolve()
    if not root.exists():  # pragma: no cover - defensive guard
        raise FileNotFoundError(f"Generated messages directory not found: {root}")

    messages: Dict[str, str] = {}
    for ros_type, relative_path in manifest.items():
        msg_path = root / relative_path
        if not msg_path.exists():  # pragma: no cover - surface configuration issues
            raise FileNotFoundError(f"Message definition not found: {msg_path}")
        messages[ros_type] = msg_path.read_text(encoding="utf-8")
    return messages


def install_in_typestore(
    manifest_path: Path,
    *,
    base_path: Path | None = None,
    typestore: Typestore | None = None,
    types_factory: Callable[[str, str], Dict[str, object]] | None = None,
) -> Dict[str, str]:
    """Register the manifest's message definitions with a rosbags typestore."""

    if types_factory is None or typestore is None:
        try:
            from rosbags.typesys import Stores, get_typestore
            from rosbags.typesys.msg import get_types_from_msg
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError("rosbags is required to install generated messages.") from exc

        if types_factory is None:
            types_factory = get_types_from_msg
        if typestore is None:
            typestore = get_typestore(Stores.ROS2_HUMBLE)

    register_fn = typestore.register

    messages = collect_messages(manifest_path, base_path=base_path)
    aggregated: Dict[str, object] = {}
    for ros_type, definition in messages.items():
        aggregated.update(types_factory(definition, ros_type))

    register_fn(aggregated)
    return messages


def validate_manifest(
    manifest_path: Path,
    *,
    base_path: Path | None = None,
    typestore: Typestore | None = None,
    types_factory: Callable[[str, str], Dict[str, object]] | None = None,
) -> Tuple[int, Iterable[str]]:
    """Validate that all manifest entries register successfully."""

    if typestore is None or types_factory is None:
        try:
            from rosbags.typesys import Stores, get_typestore
            from rosbags.typesys.msg import get_types_from_msg
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError("rosbags is required to validate generated messages.") from exc

        if typestore is None:
            typestore = get_typestore(Stores.ROS2_HUMBLE)
        if types_factory is None:
            types_factory = get_types_from_msg

    messages = install_in_typestore(
        manifest_path,
        base_path=base_path,
        typestore=typestore,
        types_factory=types_factory,
    )

    missing = _find_missing_dependencies(messages, typestore)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(
            "Missing dependent message definitions: "
            f"{missing_list}. Add these packages to msg_definitions_src and regenerate."
        )
    else:
        print("[green]All message definitions were validated.[/green]")

    return len(messages), messages.keys()


_PRIMITIVE_TYPES: Set[str] = {
    "bool",
    "byte",
    "char",
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
    "float32",
    "float64",
    "string",
    "wstring",
    "time",
    "duration",
}


def _find_missing_dependencies(messages: Dict[str, str], typestore) -> Set[str]:
    known_types: Set[str] = set(getattr(typestore, "types", {}).keys())
    known_types.update(messages.keys())

    missing: Set[str] = set()
    for ros_type, definition in messages.items():
        package, _, remainder = ros_type.partition("/msg/")
        msg_name = remainder or ""
        for dependency in _extract_dependencies(definition, package, msg_name):
            if dependency not in known_types:
                missing.add(dependency)
    return missing


def _extract_dependencies(definition: str, package: str, msg_name: str) -> Set[str]:
    dependencies: Set[str] = set()
    for raw_line in definition.splitlines():
        line, _, _ = raw_line.partition("#")
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < 2:
            continue
        type_token = tokens[0]
        dependency = _resolve_ros_type(type_token, package)
        if dependency:
            dependencies.add(dependency)
    dependencies.discard(f"{package}/msg/{msg_name}")
    return dependencies


def _resolve_ros_type(type_token: str, current_package: str) -> str | None:
    base = type_token.split("[", 1)[0]
    if base.startswith("string<=") or base.startswith("wstring<="):
        return None
    if base in _PRIMITIVE_TYPES:
        return None
    if "/" in base:
        pkg, name = base.split("/", 1)
        return f"{pkg}/msg/{name}"
    return f"{current_package}/msg/{base}"
