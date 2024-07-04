@echo off
python -m venv .venv
.\.venv\Scripts\pip3.exe install -r requirements.txt
.\.venv\Scripts\pyinstaller.exe --uac-admin --noconsole -n SRR -F --clean main.py
