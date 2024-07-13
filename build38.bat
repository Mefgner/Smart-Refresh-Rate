if not exist venv38 (
    %localappdata%\Programs\Python\Python38\python.exe -m venv venv38
    .\venv38\Scripts\pip3.exe install -r requirements.txt
    .\venv38\Scripts\pip3.exe install pyinstaller
)
.\venv38\Scripts\pyinstaller.exe --uac-admin --noconsole --clean -n SRR -F main.py