if not exist .venv (
    python -m venv .venv
    .\.venv\Scripts\pip3.exe install -r requirements.txt
    .\.venv\Scripts\pip3.exe install pyinstaller
)
.\.venv\Scripts\pyinstaller.exe --uac-admin -n SRR-test -F --clean main.py
cd .\dist\
.\SRR-test.exe
cd ..