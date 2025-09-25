from __future__ import annotations

import json
import sys
from pathlib import Path

from autoware_rosbags_converter.generate_msg_definitions import main as generate_main
from autoware_rosbags_converter.msg_definition_generator import (
    MsgDefinitionGenerator,
    build_manifest,
)


def write_pkg(
    root: Path,
    package: str,
    files: dict[str, str],
) -> Path:
    pkg_root = root / package
    pkg_root.mkdir(parents=True, exist_ok=True)
    (pkg_root / "package.xml").write_text(
        f"<package><name>{package}</name></package>",
        encoding="utf-8",
    )
    for relative, content in files.items():
        msg_path = pkg_root / relative
        msg_path.parent.mkdir(parents=True, exist_ok=True)
        msg_path.write_text(content.strip() + "\n", encoding="utf-8")
    return pkg_root


def test_generator_copies_msg_files(tmp_path):
    source_root = tmp_path / "src"
    output_root = tmp_path / "out"
    pkg_root = write_pkg(
        source_root,
        package="example_msgs",
        files={
            "msg/Example.msg": """
            uint8 FLAG_OFF = 0
            string label
            example_msgs/Example nested
            float32[<=4] points
            """,
            "msg/nested/Inner.msg": "string data",
        },
    )

    generator = MsgDefinitionGenerator(output_root=output_root)
    msg_dir = pkg_root / "msg"
    results = generator.generate_from_msg_dir("example_msgs", pkg_root, msg_dir)

    assert len(results) == 2
    ros_types = {artifact.ros_type for artifact in results}
    assert ros_types == {
        "example_msgs/msg/Example",
        "example_msgs/msg/Inner",
    }

    generated_path = output_root / "example_msgs" / "Example.msg"
    assert generated_path.exists()
    assert "FLAG_OFF" in generated_path.read_text(encoding="utf-8")

    nested_output = output_root / "example_msgs" / "nested" / "Inner.msg"
    assert nested_output.exists()
    assert "string data" in nested_output.read_text(encoding="utf-8")

    manifest = build_manifest(results, output_root=output_root)
    assert manifest == {
        "example_msgs/msg/Example": "example_msgs/Example.msg",
        "example_msgs/msg/Inner": "example_msgs/nested/Inner.msg",
    }


def test_cli_writes_relative_manifest(tmp_path, monkeypatch):
    source_root = tmp_path / "src"
    output_root = tmp_path / "out"
    manifest_path = output_root / "manifest.json"

    pkg_root = write_pkg(
        source_root,
        package="example_msgs",
        files={"msg/Example.msg": "string name"},
    )

    argv = [
        "generate-msg-definitions",
        "--source-root",
        str(source_root),
        "--output-root",
        str(output_root),
        "--manifest",
        str(manifest_path),
    ]

    monkeypatch.setattr(sys, "argv", argv)
    generate_main()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {"example_msgs/msg/Example": "example_msgs/Example.msg"}


def test_generate_from_nested_package_structure(tmp_path):
    source_root = tmp_path / "src"
    output_root = tmp_path / "out"

    pkg_root = write_pkg(
        source_root,
        package="complex_msgs",
        files={
            "vehicle/msg/State.msg": "int32 value",
            "vehicle/msg/sub/Inner.msg": "bool flag",
        },
    )

    generator = MsgDefinitionGenerator(output_root=output_root)
    msg_dir = pkg_root / "vehicle" / "msg"
    results = generator.generate_from_msg_dir("complex_msgs", pkg_root, msg_dir)

    output_files = sorted(artifact.output_path.relative_to(output_root).as_posix() for artifact in results)
    assert output_files == [
        "complex_msgs/vehicle/State.msg",
        "complex_msgs/vehicle/sub/Inner.msg",
    ]

    manifest = build_manifest(results, output_root=output_root)
    assert manifest == {
        "complex_msgs/msg/State": "complex_msgs/vehicle/State.msg",
        "complex_msgs/msg/Inner": "complex_msgs/vehicle/sub/Inner.msg",
    }
