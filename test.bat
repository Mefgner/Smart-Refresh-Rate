@echo off
python -m venv .venv
.\.venv\Scripts\pip3.exe install -r requirements.txt
.\.venv\Scripts\pyinstaller.exe -n Auto60HZ -F --clean main.py
.\dist\Auto60HZ.exe