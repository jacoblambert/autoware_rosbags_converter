import json
from pathlib import Path
from typing import Dict

import pytest

from autoware_rosbags_converter.msg_definition_generator import MsgDefinitionGenerator
from autoware_rosbags_converter.typestore import (
    collect_messages,
    install_in_typestore,
    load_manifest,
    validate_manifest,
)


def prepare_generated_package(tmp_path: Path, message_body: str | None = None) -> tuple[Path, Path]:
    source_root = tmp_path / "src"
    output_root = tmp_path / "out"
    pkg_root = source_root / "example_msgs"
    pkg_root.mkdir(parents=True, exist_ok=True)
    (pkg_root / "package.xml").write_text(
        "<package><name>example_msgs</name></package>",
        encoding="utf-8",
    )
    msg_dir = pkg_root / "msg"
    msg_dir.mkdir(parents=True, exist_ok=True)
    body = message_body or """
    uint8 FLAG = 1
    string name
    """
    (msg_dir / "Example.msg").write_text(body.strip() + "\n", encoding="utf-8")

    generator = MsgDefinitionGenerator(output_root=output_root)
    results = generator.generate_from_msg_dir("example_msgs", pkg_root, msg_dir)
    manifest = {
        artifact.ros_type: artifact.output_path.relative_to(output_root).as_posix()
        for artifact in results
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path, output_root


def test_collect_messages(tmp_path):
    manifest_path, output_root = prepare_generated_package(tmp_path)

    loaded_manifest = load_manifest(manifest_path)
    assert "example_msgs/msg/Example" in loaded_manifest

    messages = collect_messages(manifest_path, base_path=output_root)
    key = "example_msgs/msg/Example"
    assert key in messages
    assert "uint8 FLAG = 1" in messages[key]


def test_install_with_custom_register(tmp_path):
    manifest_path, output_root = prepare_generated_package(tmp_path)

    class FakeTypestore:
        def __init__(self) -> None:
            self.types: Dict[str, object] = {}

        def register(self, defs: Dict[str, object]) -> None:
            self.types.update(defs)

    fake = FakeTypestore()

    result = install_in_typestore(
        manifest_path,
        base_path=output_root,
        typestore=fake,
        types_factory=lambda definition, full_name: {full_name: definition},
    )

    assert result == fake.types
    assert "example_msgs/msg/Example" in fake.types


def test_validate_manifest_missing_dependency(tmp_path):
    manifest_path, output_root = prepare_generated_package(
        tmp_path,
        message_body="geometry_msgs/Point point\n",
    )

    class FakeTypestore:
        def __init__(self) -> None:
            self.types: Dict[str, object] = {}

        def register(self, defs: Dict[str, object]) -> None:
            self.types.update(defs)

    fake = FakeTypestore()

    with pytest.raises(ValueError) as exc:
        validate_manifest(
            manifest_path,
            base_path=output_root,
            typestore=fake,
            types_factory=lambda definition, full_name: {full_name: definition},
        )

    assert "geometry_msgs/msg/Point" in str(exc.value)
