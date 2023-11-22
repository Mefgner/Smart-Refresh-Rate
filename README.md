# Auto60HZ
## This small utility will automatically switch refresh rate you have chosen when you plug off your charger and sets it back when you plug it in

Powered by [ResChanger](https://github.com/Mefgner/ResChanger).

## Quick start
Before of all, **set your own settings** inside config.json (Do it before installing, because the file will be inserted inside .exe).
> If you have troubles with downrating refresh rate press _right_shift + del_ to set to default your screen settings and close program.

You can use installer.bat to install the program(also will add program to auto startup) or do it manually:
1. Install python(version >= 3.6, might work older versions)
2. Create virtual enviroment by
   
```batch
python -m venv venv
```
  
3. Activate enviroment

For powershell:

```shell
.\venv\Scripts\Activate.ps1
```

For batch:

```batch
venv\Sctipts\activate.bat
```

4. Install depencies

```batch
pip3 install -r requirements.txt
```

5. Compile an executable

```batch
pyinstaller -n Auto60HZ -D --add-data "config.json:." --clean main.py
```

