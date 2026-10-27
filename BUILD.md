# Building the F-204 Icarus II

The mod is two files that work only as a pair: `Icarus.dll`, the BepInEx plugin built from `src/Icarus`, and `icarus_<version>.nobp`, the Blueprinter bundle built by the Unity project in `unity/`. The bundle is authored from the mesh exports in `art/export`, so you don't need Blender unless you change the model.

The build has only been run on the developer's machine. If a step fails on yours, open an issue with the step and the error.

## What you need

- Windows, PowerShell 7 and Git.
- The .NET SDK (8 or later).
- Python 3.9 or later, available as `python`, for the export hash check.
- Unity Editor **2022.3.62f2**.
- A purchased copy of Nuclear Option **0.34.2** with BepInEx 5 installed in it. The build reads the game's assemblies and BepInEx's from there. If the game isn't at `C:\Program Files (x86)\Steam\steamapps\common\Nuclear Option`, set `NUCLEAR_OPTION_DIR` to its folder.
- An export of your game install from **AssetRipper 2.0.0** (Script Content Level **Level 1**, Script Export Format **Decompilation**). The repository holds no game assets; the build clones the FS-12 Revoker and other stock settings from your local import.

## Prepare the Unity project (once)

1. Open the `unity` folder in Unity Hub and let Unity restore its packages. Blueprinter Editor is pinned to commit `9a4a8e509480cbcde901a577985d5e9cbc570d91` in `unity/Packages/manifest.json`.
2. Open **Blueprinter > Project Setup** and enter game version `0.34.2`.
3. Choose **Import Game Assemblies** and select your `NuclearOption.exe`. Let Unity finish compiling and reload.
4. Import the game assets from your AssetRipper export's `ExportedProject/Assets` folder through Blueprinter's importer. They land in `Assets/Blueprinter/_donotship`, where the build looks stock assets up by path.
5. Import **TMP Essentials** when Unity asks.
6. Close Unity. The build runs it in batch mode and refuses while an editor has the project open.

Imported game assets, assemblies and Unity caches stay local and are ignored by git. Never commit them; the pre-commit hook (`tools/Check-Public.ps1`) rejects them.

Enable the hooks in each fresh clone, then check every tracked working-tree file before publication:

```powershell
git config core.hooksPath .githooks
pwsh -NoProfile -File tools/Check-Public.ps1 -All
```

The hook checks staged blobs. `-All` checks tracked files and untracked, non-ignored files as they are on disk. Both resolve Git LFS pointers, check binary metadata and verify export hashes. Exceptions belong in `tools/public-check-allowlist.json`, with an exact file path, rule name, literal matched values and a reason. The initial exceptions allow the checker's own machine-name rule and its allowlist entries. These checks cover the current tree, not Git history.

Texture provenance stores paths relative to the repository root. Readers resolve them against that root, independently of the working directory. After importing older records, run `python tools/Make-TextureRecordsPortable.py` to convert paths and update dependent metadata hashes. Repeating the conversion changes no files. External image-generation identifiers and native image hashes remain provenance.

Test mission generation reads `ICARUS_MISSION_TEMPLATES`, or `mission_templates` in the ignored `tools/local-paths.json`, for the framework's templates folder. Relative template paths resolve from this repository's root. The bare-metal report cites installed game source by assembly and filename, without a local checkout path.

## Build

From the repository root:

```powershell
pwsh -NoProfile -File tools/Build-Icarus.ps1
```

It checks every export against `art/export-manifest.json`, builds the plugin, copies it and BepInEx's assemblies into the Unity project, authors the aircraft from the pinned exports on the Revoker, checks the result against the authoring checklist (A1 to A21: the donor strip, stations, gear, cockpit, audio, structure and icons, one `[Icarus] check` line each in the Unity log), and builds the bundle. The last line is the verdict, `B0 PASS: build/icarus_<version>.nobp ...` or `B0 FAIL: <why>`. Unity's logs stay in `build/logs`. Pass `-UnityPath <Unity.exe>` if it can't find Unity 2022.3.62f2.

The build rewrites the authored assets under `unity/Assets/Blueprinter/Mods/icarus`; Unity regenerates their object IDs.

## Install your build

Close the game, then copy `build/Icarus.dll` and `build/icarus_<version>.nobp` into `BepInEx/plugins/baanish.icarus/` in the game folder. Blueprinter 2.1.1 or later must be installed and enabled; 2.1.1 is the version the current build is tested with. `BepInEx/LogOutput.log` names the version on load: `F-204 Icarus II <version> (baanish.icarus)`.

The flight-model knobs live in `BepInEx/config/baanish.icarus.cfg` under `[Tuning.*]`. A value below 0 is the shipped value; saving the file applies the rest to every Icarus in flight. While another player is connected, every knob reads its shipped value.

## Change the model

The model is generated by `art/blender/build_icarus.py` in Blender 5.2. From the repository root:

Before rebuilding, copy `tools/local-paths.example.json` to `tools/local-paths.json` and set `game_export` to your AssetRipper `Assets` folder. The light check raycasts the stock tip stores and lenses over 0 to 110 degrees outboard and 90 degrees above and below horizontal, at one-degree intervals. It requires zero blocked directions across each wing's upper and lower lenses. This checks geometric visibility, not the light intensities required by FAR 25.1389. Run `tools/review_navlights.py` through `tools/Run-Blender.ps1`, with `-- after`, to write the measurements and six lit views under `.cache/review/share/navlights/`.

1. `blender --background --factory-startup --python-exit-code 1 --python tools/export_blockout.py` rebuilds the aircraft and writes `art/export`.
2. `python tools/export_manifest.py --write` pins the new exports. Review and commit the manifest with the changed source and exports, then build.
3. When the outline or the damageable parts change, `python tools/status_diagram.py` redraws the damage diagram and the tac screen's front profile into `unity/Assets/Blueprinter/Mods/icarus/Diagram` and `art/diagram.json`.
4. When the outline changes, `python tools/map_icon.py` redraws the icon the map and the plane select screen show into `unity/Assets/Blueprinter/Mods/icarus/Icons`, with a sheet beside stock jets in `.cache/review/share/icons`.
