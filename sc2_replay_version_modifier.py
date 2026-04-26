from __future__ import annotations

import argparse
import bz2
import shutil
from pathlib import Path

from mpyq import MPQArchive


DEFAULT_OLD_BUILD = "96516"
DEFAULT_NEW_BUILD = "96921"
DEFAULT_OLD_GAME_VERSION = "5.0.15.96516"
DEFAULT_NEW_GAME_VERSION = "5.0.15.96921"
DEFAULT_OLD_DATA_VERSION = "B5A551ED8B1A137FFFCC2BA50EC63173"
DEFAULT_NEW_DATA_VERSION = "C83ECFF50A077219461434CF97BB5497"


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


def replace_metadata(
    metadata: bytes,
    old_build: str,
    new_build: str,
    old_game_version: str,
    new_game_version: str,
    old_data_version: str,
    new_data_version: str,
) -> bytes:
    replacements = [
        (old_game_version.encode("ascii"), new_game_version.encode("ascii")),
        (old_data_version.encode("ascii"), new_data_version.encode("ascii")),
        (f"Base{old_build}".encode("ascii"), f"Base{new_build}".encode("ascii")),
        (old_build.encode("ascii"), new_build.encode("ascii")),
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
    old_build: str,
    new_build: str,
    old_game_version: str,
    new_game_version: str,
    old_data_version: str,
    new_data_version: str,
    overwrite: bool,
) -> Path:
    archive = MPQArchive(str(path))
    metadata_name = b"replay.gamemetadata.json"
    metadata = archive.read_file(metadata_name)
    if not metadata or old_build.encode("ascii") not in metadata:
        raise ValueError(f"{path} does not look like a {old_build} replay")

    patched_metadata = replace_metadata(
        metadata,
        old_build=old_build,
        new_build=new_build,
        old_game_version=old_game_version,
        new_game_version=new_game_version,
        old_data_version=old_data_version,
        new_data_version=new_data_version,
    )

    hash_entry = archive.get_hash_table_entry(metadata_name)
    block_entry = archive.block_table[hash_entry.block_table_index]
    payload_start = archive.header["offset"] + block_entry.offset
    payload_end = payload_start + block_entry.archived_size

    compressed_metadata = compress_to_existing_size(patched_metadata, block_entry.archived_size - 1)
    new_payload = (b"\x10" + compressed_metadata).ljust(block_entry.archived_size, b"\x00")

    old_build_vint = encode_sc2_vint(int(old_build))
    new_build_vint = encode_sc2_vint(int(new_build))

    patched_file = bytearray(path.read_bytes())
    patched_file[payload_start:payload_end] = new_payload

    user_header = archive.header.get("user_data_header")
    if not user_header:
        raise RuntimeError(f"{path} has no MPQ user data header")

    content_start = 16
    content_end = content_start + user_header["user_data_header_size"]
    user_content = bytes(patched_file[content_start:content_end])
    if old_build_vint not in user_content:
        raise RuntimeError(f"could not find encoded build {old_build} in {path}")
    user_content = user_content.replace(old_build_vint, new_build_vint)
    patched_file[content_start:content_end] = user_content

    if overwrite:
        backup_path = path.with_suffix(path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
        out_path = path
    else:
        out_path = path.with_name(path.stem + f".buildonly-{new_build}" + path.suffix)

    out_path.write_bytes(patched_file)
    return out_path


def iter_input_replays(root: Path, old_build: str, new_build: str) -> list[Path]:
    skip_tokens = [
        f".buildonly-{new_build}",
        f".metaonly-{new_build}",
        f".inplace-{new_build}",
        f".spoof-{new_build}",
        ".transplant-",
    ]
    paths = []
    for path in sorted(root.rglob("*.SC2Replay")):
        if any(token in path.name for token in skip_tokens):
            continue
        try:
            archive = MPQArchive(str(path))
            metadata = archive.read_file(b"replay.gamemetadata.json")
        except Exception:
            continue
        if metadata and old_build.encode("ascii") in metadata:
            paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Patch SC2 replays from one build to another without changing DataVersion. "
            "This is the build-only method that avoids mod data mismatch."
        )
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Replay files or folders to patch")
    parser.add_argument("--old-build", default=DEFAULT_OLD_BUILD)
    parser.add_argument("--new-build", default=DEFAULT_NEW_BUILD)
    parser.add_argument("--old-game-version", default=DEFAULT_OLD_GAME_VERSION)
    parser.add_argument("--new-game-version", default=DEFAULT_NEW_GAME_VERSION)
    parser.add_argument("--old-data-version", default=DEFAULT_OLD_DATA_VERSION)
    parser.add_argument("--new-data-version", default=DEFAULT_NEW_DATA_VERSION)
    parser.add_argument("--overwrite", action="store_true", help="Patch original files and create .bak backups")
    args = parser.parse_args()

    inputs = args.paths or [Path(".")]
    replay_paths: list[Path] = []
    for item in inputs:
        if item.is_dir():
            replay_paths.extend(iter_input_replays(item, args.old_build, args.new_build))
        elif item.is_file():
            replay_paths.append(item)

    if not replay_paths:
        print("No matching replays found.")
        return

    for replay_path in replay_paths:
        try:
            out_path = patch_replay(
                replay_path,
                old_build=args.old_build,
                new_build=args.new_build,
                old_game_version=args.old_game_version,
                new_game_version=args.new_game_version,
                old_data_version=args.old_data_version,
                new_data_version=args.new_data_version,
                overwrite=args.overwrite,
            )
            print(f"patched: {replay_path} -> {out_path}")
        except Exception as exc:
            print(f"skipped: {replay_path} ({exc})")


if __name__ == "__main__":
    main()
