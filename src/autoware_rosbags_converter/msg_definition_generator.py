"""Collect ROS msg definitions into a local directory and manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class MessageArtifact:
    """Description of a generated message asset."""

    ros_type: str
    source_path: Path
    output_path: Path


class MsgDefinitionGenerator:
    """Copy ROS .msg files into a workspace and record their locations."""

    def __init__(self, *, output_root: Path) -> None:
        self.output_root = output_root

    def generate_from_msg_dir(self, package_name: str, msg_dir: Path) -> List[MessageArtifact]:
        """Copy every *.msg file from a specific msg directory."""

        if not msg_dir.is_dir():
            return []

        artifacts: List[MessageArtifact] = []
        for msg_path in sorted(msg_dir.rglob("*.msg")):
            relative = msg_path.relative_to(msg_dir)
            ros_suffix = relative.with_suffix("").as_posix()
            ros_type = f"{package_name}/msg/{ros_suffix}"

            rel_output = Path(package_name) / relative
            output_path = self.output_root / rel_output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(msg_path.read_text(encoding="utf-8"), encoding="utf-8")

            artifacts.append(
                MessageArtifact(
                    ros_type=ros_type,
                    source_path=msg_path,
                    output_path=output_path,
                )
            )
        return artifacts

    def generate_many(self, entries: Iterable[Tuple[str, Path]]) -> List[MessageArtifact]:
        """Process multiple (package, msg_dir) entries and return produced artifacts."""

        artifacts: List[MessageArtifact] = []
        for package_name, msg_dir in entries:
            artifacts.extend(self.generate_from_msg_dir(package_name, msg_dir))
        return artifacts


def build_manifest(artifacts: Iterable[MessageArtifact], *, output_root: Path) -> Dict[str, str]:
    """Create a mapping from ROS type to relative .msg path."""

    manifest: Dict[str, str] = {}
    for artifact in artifacts:
        relative = artifact.output_path.relative_to(output_root)
        manifest[artifact.ros_type] = relative.as_posix()
    return manifest
