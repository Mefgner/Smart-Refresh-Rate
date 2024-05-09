@echo off
python -m venv venv
.\venv\Scripts\pip3.exe install psutil pynput pyinstaller
.\venv\Scripts\pyinstaller.exe -n Auto60HZ --noconsole -F --clean main.py
mkdir %USERPROFILE%\AppData\Local\Auto60HZ
copy dist\Auto60HZ.exe %USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe /y
copy config.json %USERPROFILE%\AppData\Local\Auto60HZ\config.json /y
REG ADD HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Run /v Auto60HZ /t REG_SZ /d %USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe /f
%USERPROFILE%\AppData\Local\Auto60HZ\Auto60HZ.exe
