import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    result = subprocess.run(["cmd", "/c", "build.bat"], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)

    exe = ROOT / "dist" / "SRR.exe"
    subprocess.run([str(exe)], cwd=ROOT / "dist")
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
