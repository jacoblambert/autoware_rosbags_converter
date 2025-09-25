# autoware_rosbags_converter

Tools for converting Autoware rosbag2 directories (.db3) to MCAP and back, and for maintaining the ROS message definitions needed by `rosbags`.

## Installation

### pipx

```bash
pipx install .                     # from a local checkout
# or, from git (replace URL with your fork)
pipx install "git+https://github.com/<org>/autoware_mcap_db3_converter.git"
```

Update an existing pipx install with:

```bash
pipx install --force .
```
## Local development and builds

Create a virtual environment and install dependencies (including optional dev tools):

```bash
uv sync --extra dev
```

Optionally, build and install distributions with:

```bash
uv build
pip install dist/autoware_rosbags_converter-*.whl
```

## Converting bags

Use `convert-autoware-bag` on a rosbag2 (SQLite3) or MCAP directory. The tool auto-detects the input format and writes the opposite format beside it unless `--output` is provided.

```bash
convert-autoware-bag /path/to/rosbag2_dir
convert-autoware-bag /path/to/bag_mcap --output /path/to/converted_db3
```

- If message definitions are missing, the CLI displays the affected topics before proceeding.
- Pass `--force` to continue without confirmation.
- Supply `--manifest` to point at a custom `manifest.json` (defaults to the packaged definitions).
- When metadata is incomplete, you may be prompted to run `ros2 bag reindex`.

## Generating additional message definitions

The repository ships with curated definitions under `src/autoware_rosbags_converter/msg_definitions`. To add or refresh messages:

1. Drop the desired ROS packages (or symbolic links to them) under `msg_definitions_src/`.
2. Run the generator:
   ```bash
   generate-msg-definitions --validate
   ```
3. Use `--packages <pkg_dir ...>` to restrict generation to specific packages.
4. The script copies `.msg` files into `src/autoware_rosbags_converter/msg_definitions/` and rewrites `manifest.json`. Validation ensures every definition can be loaded into the Humble typestore and reports dependencies that are still missing.

Commit the updated `.msg` files and `manifest.json` when you are satisfied.

## Requesting new or updated message support

If you encounter missing message types during conversion:

- Capture the missing type list printed by `convert-autoware-bag` (or re-run with `--force` to reproduce the table).
- Open an issue or pull request and include:
  - The message type names and packages that are absent.
  - A short description of the Autoware workflow that needs them (and, when possible, a minimal bag demonstrating the topics).
  - Any upstream package sources that contain the `.msg` files (tarball link, vcs URL, etc.).

Providing that information lets maintainers add the definitions or guide you through generating them yourself.
