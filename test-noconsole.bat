if not exist .venv (
    python -m venv .venv
    .\.venv\Scripts\pip3.exe install -r requirements.txt
    .\.venv\Scripts\pip3.exe install pyinstaller
)
.\.venv\Scripts\pyinstaller.exe --noconsole -n SRR-test -F --clean main.py
.\dist\SRR-test.exe