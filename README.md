# SC2 Replay Version Modifier / SC2录像版本号修改器

Batch version-number modifier for StarCraft II replay files that fail to open after a small build-number-only update.

这是一个用于批量修改《星际争霸 II》录像版本号的小工具，适用于游戏内容没有变化、但旧录像因为无意义 build 号更新而无法打开的情况。

## What It Does / 功能

This tool patches replay metadata from build `96516` to `96921` using the verified **build-only** method:

- Updates `GameVersion`, `DataBuild`, and `BaseBuild` in `replay.gamemetadata.json`.
- Updates the build number inside the MPQ user header.
- Keeps the original MPQ user-header `DataVersion` unchanged to avoid the "mod data mismatch" error.
- Keeps the original replay file unchanged and writes a new `*.buildonly-96921.SC2Replay` file.

本工具使用已经验证可用的 **build-only** 修复方式：

- 修改 `replay.gamemetadata.json` 里的 `GameVersion`、`DataBuild`、`BaseBuild`。
- 修改 MPQ 用户头里的 build 号。
- 保留 MPQ 用户头里的原始 `DataVersion`，避免“使用过的 mod 数据不匹配”。
- 不覆盖原录像，生成新的 `*.buildonly-96921.SC2Replay` 文件。

## Download / 下载

Windows packaged build:

[release/sc2_replay_version_modifier_windows.zip](release/sc2_replay_version_modifier_windows.zip)

Windows 打包版：

[release/sc2_replay_version_modifier_windows.zip](release/sc2_replay_version_modifier_windows.zip)

## Usage / 使用方法

Unzip the Windows package, then run:

```powershell
.\sc2_replay_version_modifier.exe "C:\Path\To\ReplayFolder"
```

解压 Windows 压缩包后运行：

```powershell
.\sc2_replay_version_modifier.exe "C:\你的录像文件夹"
```

The tool recursively scans `.SC2Replay` files and creates repaired copies next to the originals.

工具会递归扫描 `.SC2Replay` 文件，并在原文件旁边生成修复后的副本。

## Source Usage / 源码运行

Install dependencies:

```powershell
python -m pip install mpyq
```

Run:

```powershell
python sc2_replay_version_modifier.py "C:\Path\To\ReplayFolder"
```

## Notes / 注意事项

- This is not a general replay converter.
- It does not change unit data, game events, map data, or mod dependency hashes.
- It is intended for very small StarCraft II version bumps where replay protocol and gameplay data remain compatible.
- If the game still rejects a replay, that replay likely needs the original SC2 build.

- 这不是通用录像转换器。
- 它不会修改单位数据、游戏事件、地图数据或 mod 依赖 hash。
- 它只适合 SC2 小版本 build 号变化，但录像协议和游戏数据仍兼容的情况。
- 如果修复后仍无法打开，通常说明该录像仍需要原始 SC2 客户端版本。

## Build / 编译

```powershell
python -m pip install pyinstaller mpyq
python -m PyInstaller --onedir --name sc2_replay_version_modifier sc2_replay_version_modifier.py
```

`--onedir` is recommended. `--onefile` can fail on some Windows systems because the bundled runtime must be extracted to a temporary directory.

推荐使用 `--onedir`。部分 Windows 环境中 `--onefile` 可能因为临时目录解包权限失败而无法启动。

## License / 许可证

MIT License.
