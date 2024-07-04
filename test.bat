@echo off
rmdir /s /q %localappdata%\SRR
if not exist .venv (
    python -m venv .venv
    .\.venv\Scripts\pip3.exe install -r requirements.txt
)
.\.venv\Scripts\pyinstaller.exe -n SRR-test -F --clean main.py
.\dist\SRR-test.exe