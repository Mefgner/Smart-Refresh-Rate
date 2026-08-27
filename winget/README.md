# winget manifest — Mefgner.SmartRefreshRate

Source manifests for submitting **Smart Refresh Rate** to the
[winget-pkgs](https://github.com/microsoft/winget-pkgs) community repository.

## Layout

```
winget/
  README.md                          # this file
  manifests/m/Mefgner/SmartRefreshRate/1.1.6.0/
    Mefgner.SmartRefreshRate.yaml                 # version
    Mefgner.SmartRefreshRate.locale.en-US.yaml    # defaultLocale
    Mefgner.SmartRefreshRate.installer.yaml       # installer (portable, x64)
```

Schema target: **ManifestVersion 1.10.0** (multi-file format).
Docs: https://learn.microsoft.com/en-us/windows/package-manager/package/manifest
and https://github.com/microsoft/winget-pkgs/tree/master/doc/manifest/schema/1.10.0 .

*Singleton* (`ManifestType: singleton`) is still accepted by `winget.exe` but has
been **deprecated** in winget-pkgs — this repo uses the required 3-file split
(version + defaultLocale + installer). See
https://github.com/microsoft/winget-pkgs/issues/181590 .

Why `portable`: `SRR.exe` is a single-file PyInstaller binary. On first run it
self-copies to `%LOCALAPPDATA%\SRR`, registers `HKCU\...\Run` autostart and a
Start Menu shortcut; `--uninstall` removes them. `InstallerType: portable` tells
winget to just place the exe under its portable package root (no silent switches
needed). No `Commands`/PATH shim is published — the app self-installs and
registers a Start Menu shortcut on first run instead.

## Filling the real SHA256 at release time

`InstallerSha256` in the installer manifest is a placeholder:

```
InstallerSha256: PLACEHOLDER_SHA256_REPLACE_AT_RELEASE_TIME
```

The real hash is only known after CI builds the release artifact. Fill it with
the value CI emits (e.g. `SRR.exe.sha256` / `Get-FileHash` output):

```powershell
# after the GitHub release is published (tag v1.1.6.0):
$Url = "https://github.com/Mefgner/Smart-Refresh-Rate/releases/download/v1.1.6.0/SRR_v1.1.6.0_win64.exe"
# option A: winget's helper (downloads + hashes)
winget hash $Url
# option B: manual
Invoke-WebRequest $Url -OutFile .\SRR_v1.1.6.0_win64.exe
(Get-FileHash .\SRR_v1.1.6.0_win64.exe -Algorithm SHA256).Hash
# then replace the placeholder in Mefgner.SmartRefreshRate.installer.yaml
```

Also verify `InstallerUrl` matches the actual release asset name
(`SRR_v<ver>_win64.exe` — see `.github/workflows/main.yml` and `build.bat`),
and that `PackageVersion` is all-numeric (`1.1.6.0`, not `1.1.6.0-test`).

## Local validation

Requires `winget` ≥ 1.4 (portable support since 1.3, zip since 1.5). On Windows:

```powershell
# validate each file (or the directory as a whole)
winget validate --manifest winget\manifests\m\Mefgner\SmartRefreshRate\1.1.6.0\Mefgner.SmartRefreshRate.yaml
winget validate --manifest winget\manifests\m\Mefgner\SmartRefreshRate\1.1.6.0\Mefgner.SmartRefreshRate.locale.en-US.yaml
winget validate --manifest winget\manifests\m\Mefgner\SmartRefreshRate\1.1.6.0\Mefgner.SmartRefreshRate.installer.yaml

# or validate the whole version folder (winget ≥ 1.6):
winget validate --manifest winget\manifests\m\Mefgner\SmartRefreshRate\1.1.6.0\
```

Validation will fail while `InstallerSha256` is still the placeholder and while
the `InstallerUrl` 404s before the release is published — this is expected.
Fill the real SHA256 and re-run; `winget validate` should then pass (it
downloads the URL to check the hash if network is available).

Alternative local tool: `wingetcreate` (`winget install wingetcreate`), or
`Komac` (https://github.com/russellbanks/Komac).

## Submitting to winget-pkgs

Final validation/submission is out-of-band — it happens in the winget-pkgs repo,
not in this repo's CI.

1. Fork https://github.com/microsoft/winget-pkgs and clone your fork.
2. Copy the version folder into your fork at:

   ```
   manifests/m/Mefgner/SmartRefreshRate/1.1.6.0/
   ```

   (same 3 files, with the real SHA256 filled).
3. Push a branch and open a PR against `microsoft/winget-pkgs:master`. The PR
   description template is auto-filled; keep the checklist. Title convention:

   ```
   New version: Mefgner.SmartRefreshRate version 1.1.6.0
   ```

   Docs: https://github.com/microsoft/winget-pkgs/blob/master/doc/Authoring.md
   and https://github.com/microsoft/winget-pkgs/blob/master/.github/PULL_REQUEST_TEMPLATE.md .
4. The winget-pkgs bot runs `winget validate` + `winget install --manifest`
   checks; address any bot comments (usually `InstallerSha256` mismatch or
   `PackageVersion` formatting).
5. After merge, users can `winget install Mefgner.SmartRefreshRate` / `winget upgrade`.

Tip: for the first submission you may use
`wingetcreate submit --prtitle "New version: Mefgner.SmartRefreshRate version 1.1.6.0"`
to automate fork/PR creation, or `Komac submit`.

## Notes

- Do **not** invent a SHA256 — the placeholder intentionally blocks accidental
  submission before the release artifact exists.
- Keep `ManifestVersion` and the three-file split consistent; do not add a
  singleton file alongside them.
- Subsequent versions: duplicate the `1.1.6.0` folder to `1.1.7.0`, bump
  `PackageVersion`, update `InstallerUrl`, recompute `InstallerSha256`, and
  update `ReleaseNotes`/`ReleaseNotesUrl`.
