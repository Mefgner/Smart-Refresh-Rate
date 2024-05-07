@echo off
python -m venv venv
.\venv\Scripts\pip3.exe install psutil pynput pyinstaller
.\venv\Scripts\pyinstaller.exe -n Auto60HZ --noconsole -F --add-data "config.json:." --clean main.py
mkdir %USERPROFILE%\AppData\Local\Auto60HZ
copy dist\Auto60HZ.exe %USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe /y
REG ADD HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Run /v Auto60HZ /t REG_SZ /d %USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe /f