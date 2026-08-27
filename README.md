# Smart Refresh Rate

A small Windows utility that automatically switches your display's refresh rate: a power-saving mode when the charger is unplugged, and your preferred high-refresh mode when it's plugged back in.

## How it works

- Polls the power state once every 5 seconds.
- On battery it applies each monitor's `powersave-state` mode; on AC power, its `performance-state` mode.
- Lives in the system tray. Idle CPU usage is effectively 0% — `config.json` is only re-read when the file changes.

## Requirements

- Windows 10/11 (x64)
- A laptop with a battery (with no battery info available there is nothing to react to)
- No administrator privileges required — runs asInvoker; writes only to HKCU (autostart / uninstall registry) and uses `ChangeDisplaySettingsExA` to switch modes. No UAC prompt.

## Quick start

1. Download `SRR.exe` from the [latest release](https://github.com/Mefgner/Smart-Refresh-Rate/releases/latest).
2. Run it once — it copies itself to `%LOCALAPPDATA%\SRR`, adds itself to autostart, creates a Start Menu shortcut and registers an uninstall entry. After that the downloaded file can be deleted.
3. On first launch it generates `config.json` from your monitor's current settings and starts working right away.

## Configuration

`%LOCALAPPDATA%\SRR\config.json` contains one entry per monitor, keyed by the monitor's hardware ID:

```json
{
    "MONITOR\\LGD0521\\4&abc&0&UID0": {
        "performance-state": { "width": 2560, "height": 1440, "refresh_rate": 165 },
        "powersave-state": { "width": 2560, "height": 1440, "refresh_rate": 60 }
    }
}
```

Edit it with any text editor — SRR picks up changes automatically within a few seconds. Monitors connected later are appended to the config automatically.

## Command-line flags

```
SRR.exe --uninstall   # remove autostart, Start Menu shortcut, uninstall registry key and %LOCALAPPDATA%\SRR, restore default display modes
SRR.exe --version     # print the bundled version (from version.py) and exit
SRR.exe --config      # print the config file path (%LOCALAPPDATA%\SRR\config.json) and exit
```

Flags can also be combined with the installed copy: `%LOCALAPPDATA%\SRR\SRR.exe --version`.

## Updates

- SRR checks for updates automatically on startup and every 24 hours (via `https://api.github.com/repos/Mefgner/Smart-Refresh-Rate/releases/latest`).
- Tray menu shows **Check for updates** when up to date. When a newer release is found it changes to **Update available: vX.Y.Z**.
- Clicking **Update available: vX.Y.Z** opens the [releases page](https://github.com/Mefgner/Smart-Refresh-Rate/releases/latest) in your browser. It does not auto-download or auto-install — download and replace the exe manually.

## Logs

Runtime logs are written to `%LOCALAPPDATA%\SRR\logs.txt` (rotating file, 1 MB × 3 backups). Open it from the tray menu **Open logs** or directly in a text editor. The **Open config folder** tray item opens `%LOCALAPPDATA%\SRR`.

## FAQ

**How do I change settings?**
Edit `%LOCALAPPDATA%\SRR\config.json` (the tray menu has an **Open config folder** shortcut), then pick **Reload** — or just wait a few seconds.

**How do I pause or close it?**
Right-click the tray icon: **Pause/Resume** temporarily disables switching, **Exit** quits. On exit your displays are restored to their default modes. The **Run at startup** checkbox toggles autostart.

**Can I disable notifications?**
Yes — tray menu **Notifications** toggles them on/off (persisted in `config.json` as `notifications`, default `true`). When off, SRR still switches modes but suppresses tray balloons (config errors, update notices, etc.).

**What if I launch it twice?**
SRR is single-instance (Windows named mutex via `CreateMutexW`). Launching a second instance shows a message box — "SRR is already running (check the system tray)" — and exits. No second icon is created.

**How heavy is it on the CPU?**
SRR polls the power state once every 5 seconds and only reads `config.json` when its timestamp changes, so idle CPU usage is effectively 0%.

## Antivirus false positives

SRR ships as a single-file executable built with [PyInstaller](https://pyinstaller.org/). PyInstaller-packed binaries are a common target of heuristic antivirus detections, so some antivirus products may flag `SRR.exe` as suspicious even though there is no malware in it. If you see such a warning:

- build the executable yourself from source (see below) — this guarantees the binary matches the code in this repository;
- or add an exclusion for `SRR.exe` in your antivirus settings;
- or report the false positive to your antivirus vendor.

## Uninstall

Use **Settings → Apps → Installed apps → Smart Refresh Rate → Uninstall**, or run `%LOCALAPPDATA%\SRR\SRR.exe --uninstall`. This stops the app, removes autostart, the Start Menu shortcut, the registry entry and the install folder, and restores default display modes.

## Building from source

Requires Python 3.12. Run:

```
build.bat
```

The script creates a `.venv`, installs dependencies and produces `dist\SRR.exe` via PyInstaller.

## License

[MIT](LICENSE). Monitor icon by [Maniprasanth — Flaticon](https://www.flaticon.com/free-icons/ekg-monitor).
