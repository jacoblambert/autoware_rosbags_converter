"""Convert between Autoware rosbag2 (sqlite3) and MCAP bag directories."""

from __future__ import annotations

import argparse
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yaml
from rich import box
from rich.console import Console
from rich.table import Table
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from rosbags.rosbag2 import Reader, StoragePlugin, Writer
from rosbags.typesys import Stores, get_typestore

from autoware_rosbags_converter.typestore import install_in_typestore

console = Console()

@dataclass
class ConversionPlan:
    """Conversion parameters derived from user input."""

    input_dir: Path
    output_dir: Path
    storage: str  # "sqlite3" or "mcap"

class ConvertAutowareRosbags:
    """Convert Autoware rosbag2 directories to MCAP and vice versa."""

    def __init__(self, *, manifest_path: Optional[Path] = None, console: Optional[Console] = None) -> None:
        self.console = console or Console()
        self._resource_stack: Optional[ExitStack] = None
        if manifest_path is None:
            self.manifest_path = files("autoware_rosbags_converter") / "msg_definitions" / "manifest.json"
        else:
            self.manifest_path = manifest_path.resolve()

        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found at {self.manifest_path}")

        self.typestore = get_typestore(Stores.ROS2_HUMBLE)
        install_in_typestore(self.manifest_path, base_path=self.manifest_path.parent, typestore=self.typestore)

    def close(self) -> None:
        if self._resource_stack is not None:
            self._resource_stack.close()
            self._resource_stack = None

    def run(self, input_dir: Path, *, output_dir: Optional[Path] = None, force: bool = False) -> None:
        plan = self._prepare_plan(input_dir, output_dir)
        target = "MCAP" if plan.storage == "sqlite3" else "SQLITE3"
        self.console.print(f"[bold]Converting {plan.input_dir} to {target}[/bold]")
        self.console.print(f"[bold]Output:[/bold] {plan.output_dir}")

        if plan.storage == "sqlite3":
            self._convert_sqlite_to_mcap(plan, force=force)
        else:
            self._convert_mcap_to_sqlite(plan, force=force)

    def _prepare_plan(self, input_dir: Path, output_dir: Optional[Path]) -> ConversionPlan:
        bag_dir = input_dir.resolve()
        if not bag_dir.is_dir():
            raise ValueError("Input must be a bag directory containing metadata and data files.")

        storage = self._ensure_bag_readable(bag_dir)

        if storage == "sqlite3":
            default_name = bag_dir.name if bag_dir.name.endswith("_mcap") else f"{bag_dir.name}_mcap"
        else:
            base = bag_dir.name[:-len("_mcap")] if bag_dir.name.endswith("_mcap") else bag_dir.name
            default_name = f"{base}_db3"

        resolved_output = output_dir.resolve() if output_dir else bag_dir.parent / default_name
        return ConversionPlan(input_dir=bag_dir, output_dir=resolved_output, storage=storage)

    def _ensure_bag_readable(self, bag_dir: Path) -> str:
        metadata_path = bag_dir / "metadata.yaml"
        db_files = sorted(bag_dir.glob("*.db3"))
        mcap_files = sorted(bag_dir.glob("*.mcap"))

        if db_files and mcap_files:
            raise ValueError(
                f"Both .db3 and .mcap files detected in {bag_dir}. Provide a bag containing only one format."
            )

        expected_storage = "sqlite3" if db_files else "mcap" if mcap_files else None
        if expected_storage is None:
            raise FileNotFoundError(f"No .db3 or .mcap files found in {bag_dir}.")

        if not metadata_path.exists():
            self.console.print(f"[yellow]metadata.yaml missing in {bag_dir}.[/yellow]")
            if self._confirm_reindex(bag_dir, expected_storage):
                self._run_reindex(bag_dir, expected_storage)
            else:
                raise FileNotFoundError("metadata.yaml is required to continue.")

        metadata = self._load_metadata(metadata_path)
        info = metadata.get("rosbag2_bagfile_information", {})
        storage_id = (info.get("storage_identifier", "") or "").strip().lower()

        if not storage_id:
            self.console.print(f"[yellow]storage_identifier missing in {metadata_path}.[/yellow]")
            if self._confirm_reindex(bag_dir, expected_storage):
                self._run_reindex(bag_dir, expected_storage)
                metadata = self._load_metadata(metadata_path)
                info = metadata.get("rosbag2_bagfile_information", {})
                storage_id = (info.get("storage_identifier", "") or "").strip().lower()
            else:
                raise ValueError("storage_identifier missing. Reindex the bag to continue.")

        storage_id = storage_id or expected_storage
        if storage_id not in {"sqlite3", "mcap"}:
            raise ValueError(f"Unsupported storage identifier '{storage_id}'.")

        if storage_id == "sqlite3" and not db_files:
            raise FileNotFoundError(f"No .db3 files found in {bag_dir}.")
        if storage_id == "mcap" and not mcap_files:
            raise FileNotFoundError(f"No .mcap files found in {bag_dir}.")

        return storage_id

    # -- conversions --
    def _convert_sqlite_to_mcap(self, plan: ConversionPlan, *, force: bool) -> None:
        if plan.output_dir.exists() and any(plan.output_dir.iterdir()):
            raise FileExistsError(f"Output directory {plan.output_dir} already exists and is not empty.")

        output_writer = Writer(plan.output_dir, storage_plugin=StoragePlugin.MCAP, version=9)

        with Reader(plan.input_dir) as reader, output_writer as writer:
            allowed, missing = self._partition_connections(reader.connections)
            if missing:
                self._report_missing(missing)
                if not force and not self._confirm("Proceed without missing message definitions?", default=False):
                    self.console.print("Aborting conversion.")
                    return

            conn_map = self._register_connections(writer, allowed)
            total_messages = self._sum_message_counts(allowed)
            progress = self._build_progress()
            with progress:
                task = progress.add_task("[blue]Converting to MCAP", total=total_messages)
                for connection, timestamp, rawdata in reader.messages(connections=allowed):
                    writer.write(conn_map[connection.id], timestamp, rawdata)
                    progress.advance(task)

        self.console.print("[green]Conversion complete.[/green]")

    def _convert_mcap_to_sqlite(self, plan: ConversionPlan, *, force: bool) -> None:
        if plan.output_dir.exists() and any(plan.output_dir.iterdir()):
            raise FileExistsError(f"Output directory {plan.output_dir} already exists and is not empty.")

        output_writer = Writer(plan.output_dir, storage_plugin=StoragePlugin.SQLITE3, version=9)

        with Reader(plan.input_dir) as reader, output_writer as writer:
            allowed, missing = self._partition_connections(reader.connections)
            if missing:
                self._report_missing(missing)
                if not force and not self._confirm("Proceed without missing message definitions?", default=False):
                    self.console.print("Aborting conversion.")
                    return

            conn_map = self._register_connections(writer, allowed)
            total_messages = self._sum_message_counts(allowed)
            progress = self._build_progress()
            with progress:
                task = progress.add_task("[blue]Converting to rosbag2", total=total_messages)
                for connection, timestamp, rawdata in reader.messages(connections=allowed):
                    writer.write(conn_map[connection.id], timestamp, rawdata)
                    progress.advance(task)

        self.console.print("[green]Conversion complete.[/green]")

    # -- utilities --

    def _partition_connections(self, connections) -> Tuple[List, List]:
        known_types = set(getattr(self.typestore, "types", {}).keys())
        allowed: List = []
        missing: List = []
        for connection in connections:
            if connection.msgtype in known_types:
                allowed.append(connection)
            else:
                missing.append(connection)
        return allowed, missing

    def _report_missing(self, missing) -> None:
        table = Table(title="Missing message definitions", box=box.SIMPLE_HEAVY)
        table.add_column("Topic")
        table.add_column("Type")
        for connection in missing:
            table.add_row(connection.topic, connection.msgtype)
        self.console.print(table)

    def _register_connections(self, writer: Writer, connections) -> Dict[int, int]:
        conn_map: Dict[int, int] = {}
        for connection in connections:
            kwargs = {}
            metadata = getattr(connection, "metadata", None)
            if metadata is not None:
                kwargs["metadata"] = metadata
            qos = getattr(connection, "offered_qos_profiles", None)
            if qos is not None:
                kwargs["offered_qos_profiles"] = qos
            try:
                new_id = writer.add_connection(
                    connection.topic,
                    connection.msgtype,
                    typestore=self.typestore,
                    **kwargs,
                )
            except TypeError:
                new_id = writer.add_connection(
                    connection.topic,
                    connection.msgtype,
                    typestore=self.typestore,
                )
            conn_map[connection.id] = new_id
        return conn_map

    def _sum_message_counts(self, connections) -> Optional[int]:
        total = 0
        for connection in connections:
            msgcount = getattr(connection, "msgcount", None)
            if msgcount is None:
                stats = getattr(connection, "statistics", None)
                msgcount = getattr(stats, "message_count", None) if stats else None
            if msgcount is None:
                return None
            total += msgcount
        return total

    def _build_progress(self) -> Progress:
        return Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )

    def _load_metadata(self, metadata_path: Path) -> Dict:
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse {metadata_path}: {exc}") from exc

    def _run_reindex(self, bag_dir: Path, storage_id: str) -> None:
        command = ["ros2", "bag", "reindex", str(bag_dir), "--storage-id", storage_id]
        self.console.print("[cyan]Executing:[/cyan] " + " ".join(command))
        proc = subprocess.run(command, check=False)
        if proc.returncode != 0:
            raise RuntimeError("ros2 bag reindex failed. Inspect the bag and retry.")

    def _confirm_reindex(self, bag_dir: Path, storage_id: str) -> bool:
        return self._confirm(
            f"Run 'ros2 bag reindex {bag_dir} --storage-id {storage_id}'?",
            default=True,
        )

    def _confirm(self, prompt: str, *, default: bool) -> bool:
        indicator = "Y/n" if default else "y/N"
        while True:
            response = input(f"{prompt} [{indicator}]: ").strip().lower()
            if not response:
                return default
            if response in {"y", "yes"}:
                return True
            if response in {"n", "no"}:
                return False
            self.console.print("Please answer 'y' or 'n'.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to a rosbag2 (.db3) or MCAP bag directory.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output directory (defaults to sibling with inverted format).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional manifest path (defaults to packaged resources).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts when message definitions are missing.",
    )
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = parse_args()
    converter = ConvertAutowareRosbags(manifest_path=args.manifest, console=console)
    try:
        converter.run(args.input, output_dir=args.output, force=args.force)
    finally:
        converter.close()


if __name__ == "__main__":  # pragma: no cover
    main()
