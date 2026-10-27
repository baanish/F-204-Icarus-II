# Releasing F-204 Icarus II

Releases come from [baanish/F-204-Icarus-II](https://github.com/baanish/F-204-Icarus-II). Build locally with Unity and the purchased game's assemblies, following [BUILD.md](../BUILD.md). Only `Publish-Release.ps1` publishes anything, and only when you run it.

## Package a release

Set the same numeric version in `src/Icarus/IcarusPlugin.cs`, `src/Icarus/Icarus.csproj`, `unity/Assets/Blueprinter/Mods/icarus/modinfo.json` and the first entry of `CHANGELOG.md`. Commit the release source, including the pinned exports. Close the Unity editor for this checkout.

To package from a worktree, first run `pwsh -NoProfile -File tools/Link-WorktreeAssets.ps1` and provide the ignored `tools/local-paths.json` described in BUILD.md. Each checkout writes its own `build/` and `.cache/release/`.

```powershell
pwsh -NoProfile -File tools/Package-Release.ps1
```

The command refuses to run while any tracked file is modified or any untracked file exists. It then checks the versions and the export manifest, runs the offline release tests and builds both payloads with `tools/Build-Icarus.ps1`. Because the tree is clean, the build's inputs are the release commit's files. The build must leave every tracked input unchanged except the prefab fileIDs Unity regenerates. Text hashes normalize CRLF line endings before comparing. To change an existing CRLF file with Python, use `read_bytes` and `write_bytes` so its line endings survive.

The final line must say `RELEASE PASS`. Outputs are under `.cache/release/v<version>-<UTC time>/`:

| File | Purpose |
| --- | --- |
| `Icarus-v<version>-nomm.zip` | Flat payload. NOMM supplies the install folder. |
| `Icarus-v<version>-plugin-only.zip` | Manual install. Unzip it beside `NuclearOption.exe`, and its entries land in `BepInEx/plugins/baanish.icarus/`. |
| `SHA256SUMS.txt` | SHA-256 hashes of both archives and of `RELEASE-NOTES.md`. |
| `RELEASE-NOTES.md` | Prerelease notes with absolute source and download links. |

Both archives contain exactly `Icarus.dll`, `icarus_<version>.nobp`, `meta.json`, `README.md`, `LICENSE`, `audio/CREDITS.md` and `fonts/OFL.txt`. The DLL and bundle stay together when NOMM enables or disables the mod. Entries are sorted and carry fixed timestamps, so identical payloads produce byte-identical archives.

The output directory also holds staging copies of `meta.json` and `README.md`, already inside both ZIPs. Do not upload these separately. `meta.json` identifies the mod as `baanish.icarus`, records the full source commit and the hashes of the DLL and bundle actually shipped, and declares Blueprinter `com.nikkorap.blueprinter`, minimum `2.1.1`, in `artifact.dependencies`. Blueprinter and BepInEx are separate prerequisites and are never bundled. It holds no absolute paths and no enabled state.

Options:

- `-NotesFile <markdown-file>` adds release-specific changes to the notes.
- `-CheckOnly` checks the tree, versions, credits and exports without building.
- `-AllowDirty` permits an uncommitted local rehearsal. Archive names and the output directory carry `-LOCAL`, and `meta.json` records `local: true`. `sourceCommit` then identifies the base commit, not all payload changes. Version disagreement and build failures still stop packaging. These outputs cannot be published.
- `-SkipBuild -AllowDirty` reuses this checkout's `build/Icarus.dll` and `build/icarus_<version>.nobp` after checking their hashes against `build/SHA256SUMS.txt`. It is for testing the packaging step with fixed artifacts. Publishable packages always require a fresh build.

## Packaging is reproducible, Unity builds are not

Packaging the same built artifacts twice produces byte-identical ZIPs. To check this, build once, then run `pwsh -NoProfile -File tools/Package-Release.ps1 -AllowDirty -SkipBuild` twice and compare the ZIP hashes printed by both runs.

Full Unity rebuilds are not byte-reproducible: authoring regenerates prefab object identifiers, which changes the `.nobp` bytes. A release records its source commit and the hashes of the binaries it actually ships. The sorted entries and fixed ZIP timestamps guarantee reproducible packaging of those binaries, not reproducible Unity authoring.

## Verify a package

Verify a release without Unity:

```powershell
pwsh -NoProfile -File tools/Verify-Release.ps1 -Directory <package-directory> -Tag v0.1.0
```

For `-LOCAL` outputs, add `-AllowLocal` and keep the numeric tag. Verification checks checksums, exact paths, fixed timestamps, entry order, paired payloads, credits, dependency metadata and the embedded commit.

## Publish after owner approval

Keep releases as prereleases until multiplayer is tested on two PCs. Packaging checks do not establish gameplay or multiplayer compatibility.

Push the reviewed source and tag that exact commit `v<version>`. The repository must be public with matching unobfuscated source before publication. Then, after the owner authorizes publishing:

```powershell
pwsh -NoProfile -File tools/Publish-Release.ps1 -Directory <package-directory> -Tag v0.1.0
```

The publisher verifies local assets, checks that the existing remote tag matches `meta.json`'s source commit, creates a draft prerelease, and uploads the NOMM ZIP first. It checks every uploaded size and SHA-256 digest and the full returned asset order before publishing. Asset names sort with the NOMM ZIP first for catalog discovery. A failed upload or draft check leaves the draft unpublished for inspection.

After publication it verifies the returned tag, URL, prerelease flag, asset order and digests, then downloads the NOMM ZIP and compares its hash. It never creates tags or pushes source. NOMM catalog registration is a separate first-release task.
