# Smart Refresh Rate
### This small utility that will automatically switch refresh rate of your screen you have chosen when you plug off your charger and sets it back when you plug it in.

## Quick start
Just install exe and run it whethever you want and it will install it in user folder and add itself to autorun. Also it will create `config.json` file which contains what resolution and min/max refresh rate your monitor has to perform.

## Fast Q/A

### What if i want to set anoter settings?
Just go to path: `%localappdata%\SRR` and edit `config.json`(using notepad or whatever). Programm will auto accept changes.

### What if i want to close this program?
SRR runs with a system tray icon. Right-click it and choose **Exit**. From the same menu you can pause/resume the service, reload `config.json`, open the config folder or logs, and toggle **Run at startup** to remove SRR from Windows autostart.

### How heavy is it on the CPU?
SRR polls power state once every 5 seconds and only reads `config.json` when its mtime changes (or on demand from the tray menu), so idle CPU usage is effectively 0%.

<a href="https://www.flaticon.com/free-icons/ekg-monitor" title="monitor icons">Monitor icons created by Maniprasanth - Flaticon</a>