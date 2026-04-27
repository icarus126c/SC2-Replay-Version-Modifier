from __future__ import annotations

import argparse
import bz2
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from mpyq import MPQArchive


DEFAULT_OLD_BUILD = "96516"
DEFAULT_NEW_BUILD = "96921"
DEFAULT_OLD_GAME_VERSION = "5.0.15.96516"
DEFAULT_NEW_GAME_VERSION = "5.0.15.96921"
DEFAULT_OLD_DATA_VERSION = "B5A551ED8B1A137FFFCC2BA50EC63173"
DEFAULT_NEW_DATA_VERSION = "C83ECFF50A077219461434CF97BB5497"


@dataclass(frozen=True)
class ReplayVersionInfo:
    game_version: str
    data_build: str
    data_version: str
    base_build: str


def encode_sc2_vint(value: int) -> bytes:
    """Encode the unsigned values used in SC2 versioned user headers."""
    first = (value & 0x3F) << 1
    value >>= 6
    out = bytearray([first | (0x80 if value else 0)])
    while value:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
    return bytes(out)


def read_replay_metadata(path: Path) -> tuple[MPQArchive, bytes, dict]:
    archive = MPQArchive(str(path))
    metadata = archive.read_file(b"replay.gamemetadata.json")
    if not metadata:
        raise ValueError(f"{path} has no replay.gamemetadata.json")
    return archive, metadata, json.loads(metadata)


def version_info_from_metadata(metadata_json: dict) -> ReplayVersionInfo:
    data_build = str(metadata_json["DataBuild"])
    return ReplayVersionInfo(
        game_version=str(metadata_json["GameVersion"]),
        data_build=data_build,
        data_version=str(metadata_json["DataVersion"]),
        base_build=str(metadata_json.get("BaseBuild", f"Base{data_build}")),
    )


def replace_metadata(
    metadata: bytes,
    source: ReplayVersionInfo,
    target: ReplayVersionInfo,
) -> bytes:
    replacements = [
        (source.game_version.encode("ascii"), target.game_version.encode("ascii")),
        (source.data_version.encode("ascii"), target.data_version.encode("ascii")),
        (source.base_build.encode("ascii"), target.base_build.encode("ascii")),
        (source.data_build.encode("ascii"), target.data_build.encode("ascii")),
    ]
    patched = metadata
    for old, new in replacements:
        patched = patched.replace(old, new)
    return patched


def compress_to_existing_size(metadata: bytes, capacity: int) -> bytes:
    compressed = bz2.compress(metadata)
    if len(compressed) <= capacity:
        return compressed

    # Keep JSON byte length unchanged while nudging a few display-only values
    # into forms that compress better. JSON allows whitespace after numbers.
    for old, new in [
        (b"116.000000", b"116.0     "),
        (b"0.000000", b"0.0     "),
        (b"177.000000", b"177.0     "),
        (b"309.000000", b"309.0     "),
        (b"4814", b"4   "),
        (b"-36400", b"-3    "),
        (b"2800", b"2   "),
        (b"4461", b"4   "),
        (b"Old Republic LE", b"Old Republic   "),
        (b"White Rabbit LE", b"White Rabbit   "),
    ]:
        if old in metadata:
            candidate = metadata.replace(old, new, 1)
            compressed = bz2.compress(candidate)
            if len(compressed) <= capacity:
                return compressed
            metadata = candidate

    raise RuntimeError(
        f"patched replay.gamemetadata.json does not fit the original MPQ block "
        f"({len(compressed)} > {capacity})."
    )


def patch_replay(
    path: Path,
    target: ReplayVersionInfo,
    overwrite: bool,
) -> Path:
    metadata_name = b"replay.gamemetadata.json"
    archive, metadata, metadata_json = read_replay_metadata(path)
    source = version_info_from_metadata(metadata_json)
    if source.data_build == target.data_build:
        raise ValueError(f"{path} already uses build {target.data_build}")

    patched_metadata = replace_metadata(metadata, source=source, target=target)

    hash_entry = archive.get_hash_table_entry(metadata_name)
    block_entry = archive.block_table[hash_entry.block_table_index]
    payload_start = archive.header["offset"] + block_entry.offset
    payload_end = payload_start + block_entry.archived_size

    compressed_metadata = compress_to_existing_size(patched_metadata, block_entry.archived_size - 1)
    new_payload = (b"\x10" + compressed_metadata).ljust(block_entry.archived_size, b"\x00")

    old_build_vint = encode_sc2_vint(int(source.data_build))
    new_build_vint = encode_sc2_vint(int(target.data_build))

    patched_file = bytearray(path.read_bytes())
    patched_file[payload_start:payload_end] = new_payload

    user_header = archive.header.get("user_data_header")
    if not user_header:
        raise RuntimeError(f"{path} has no MPQ user data header")

    content_start = 16
    content_end = content_start + user_header["user_data_header_size"]
    user_content = bytes(patched_file[content_start:content_end])
    if old_build_vint not in user_content:
        raise RuntimeError(f"could not find encoded build {source.data_build} in {path}")
    user_content = user_content.replace(old_build_vint, new_build_vint)
    patched_file[content_start:content_end] = user_content

    if overwrite:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
        out_path = path
    else:
        out_path = path.with_name(path.stem + f".buildonly-{target.data_build}" + path.suffix)

    out_path.write_bytes(patched_file)
    return out_path


def iter_input_replays(root: Path, target: ReplayVersionInfo, target_replay: Path | None) -> list[Path]:
    skip_tokens = [
        ".buildonly-",
        ".metaonly-",
        ".inplace-",
        ".spoof-",
        ".transplant-",
    ]
    target_resolved = target_replay.resolve() if target_replay else None
    paths = []
    for path in sorted(root.rglob("*.SC2Replay")):
        if any(token in path.name for token in skip_tokens):
            continue
        if target_resolved and path.resolve() == target_resolved:
            continue
        try:
            _, _, metadata_json = read_replay_metadata(path)
            source = version_info_from_metadata(metadata_json)
        except Exception:
            continue
        if source.data_build != target.data_build:
            paths.append(path)
    return paths


def default_target_from_args(args: argparse.Namespace) -> ReplayVersionInfo:
    return ReplayVersionInfo(
        game_version=args.new_game_version,
        data_build=args.new_build,
        data_version=args.new_data_version,
        base_build=f"Base{args.new_build}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch SC2 replays from one build to another without changing DataVersion. "
            "This is the build-only method that avoids mod data mismatch."
        )
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Replay files or folders to patch")
    parser.add_argument(
        "-t",
        "--target-replay",
        type=Path,
        help="A replay from the new SC2 version. Its version metadata becomes the patch target.",
    )
    parser.add_argument("--old-build", default=DEFAULT_OLD_BUILD)
    parser.add_argument("--new-build", default=DEFAULT_NEW_BUILD)
    parser.add_argument("--old-game-version", default=DEFAULT_OLD_GAME_VERSION)
    parser.add_argument("--new-game-version", default=DEFAULT_NEW_GAME_VERSION)
    parser.add_argument("--old-data-version", default=DEFAULT_OLD_DATA_VERSION)
    parser.add_argument("--new-data-version", default=DEFAULT_NEW_DATA_VERSION)
    parser.add_argument("--overwrite", action="store_true", help="Patch original files and create .bak backups")
    args = parser.parse_args()

    if args.target_replay:
        _, _, target_metadata_json = read_replay_metadata(args.target_replay)
        target = version_info_from_metadata(target_metadata_json)
        print(
            "target replay: "
            f"{args.target_replay} -> {target.game_version}, build {target.data_build}, "
            f"data version {target.data_version}"
        )
    else:
        target = default_target_from_args(args)

    inputs = args.paths or [Path(".")]
    replay_paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            replay_paths.extend(iter_input_replays(item, target, args.target_replay))
        elif item.is_file():
            if not args.target_replay or item.resolve() != args.target_replay.resolve():
                replay_paths.append(item)

    if not replay_paths:
        print("No matching replays found.")
        return

    for replay_path in replay_paths:
        try:
            out_path = patch_replay(
                replay_path,
                target=target,
                overwrite=args.overwrite,
            )
            print(f"patched: {replay_path} -> {out_path}")
        except Exception as exc:
            print(f"skipped: {replay_path} ({exc})")


if __name__ == "__main__":
    main()
