@echo off
python -m venv .venv
.\.venv\Scripts\activate
py -m pip install -r requirements.txt
py -m pyinstaller -n Auto60HZ --noconsole -F --clean --add-data "config.json;." main.py
mkdir %localappdata%\Auto60HZ
copy dist\Auto60HZ.exe %localappdata%\Auto60HZ\Auto60HZ.exe /Y
copy config.json %localappdata%\Auto60HZ\config.json /Y
REG ADD HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Run /v Auto60HZ /t REG_SZ /d %USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe /f
