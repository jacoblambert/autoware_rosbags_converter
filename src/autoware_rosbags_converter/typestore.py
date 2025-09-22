"""Helpers to register generated ROS .msg files with rosbags typestores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Tuple

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

    messages = install_in_typestore(
        manifest_path,
        base_path=base_path,
        typestore=typestore,
        types_factory=types_factory,
    )
    return len(messages), messages.keys()
