if not exist .venv (
    py -3.12 -m venv .venv
    .\.venv\Scripts\pip3.exe install -r requirements.txt
)
.\.venv\Scripts\pyinstaller.exe --noconsole --clean -n SRR -F --version-file version_info.txt --add-data "assets/icon.png;assets" main.py