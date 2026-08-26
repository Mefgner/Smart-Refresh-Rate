#!/usr/bin/env python3
"""
tools/vt_check.py — upload a file to VirusTotal and poll the result.

Usage:
  python tools/vt_check.py dist/SRR.exe
  python tools/vt_check.py --hash 60a081ebd310fc473d9ddd1982c8361507c79159be595470543e9d848b5cd68d
  python tools/vt_check.py dist/SRR.exe --apikey YOUR_KEY   # overrides env/.env

API key resolution (first match wins):
  1. --apikey argument
  2. VT_API_KEY env var
  3. .env file in repo root (line VT_API_KEY=...)

Free VT API limits: ~4 req/min, 500 req/day, file <32 MB. This script
does one upload + polling, so keep it for releases, not every commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


VT_UPLOAD_URL = "https://www.virustotal.com/api/v3/files"
VT_FILE_URL = "https://www.virustotal.com/api/v3/files/{sha256}"
VT_ANALYSIS_URL = "https://www.virustotal.com/api/v3/analyses/{id}"


def load_api_key(cli_key: str | None) -> str | None:
    if cli_key:
        return cli_key.strip()
    env_key = os.getenv("VT_API_KEY")
    if env_key:
        return env_key.strip()
    # try .env next to repo root (two levels up from tools/)
    for p in [Path(".env"), Path(__file__).resolve().parents[1] / ".env"]:
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("VT_API_KEY"):
                        _, _, val = line.partition("=")
                        val = val.strip().strip('"').strip("'")
                        if val:
                            return val
            except OSError:
                pass
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def vt_request(url: str, api_key: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    hdrs = {"x-apikey": api_key, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body.decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace") if e.fp else ""
        try:
            detail = json.loads(body)
        except Exception:
            detail = body[:500]
        raise RuntimeError(f"VT {e.code} {e.reason}: {detail}") from e


def upload_file(path: Path, api_key: str) -> str:
    # multipart/form-data — build manually to avoid `requests` dependency
    boundary = "----VtBoundary7MA4YWxkTrZu0gW"
    body_parts: list[bytes] = []
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode()
    )
    body_parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    body_parts.append(path.read_bytes())
    body_parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(body_parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    print(f"Uploading {path} ({path.stat().st_size / 1_048_576:.2f} MB) ...")
    resp = vt_request(VT_UPLOAD_URL, api_key, data=body, headers=headers)
    analysis_id = resp["data"]["id"]
    print(f"  analysis id: {analysis_id}")
    return analysis_id


def poll_analysis(analysis_id: str, api_key: str, timeout: int = 300) -> dict:
    url = VT_ANALYSIS_URL.format(id=analysis_id)
    start = time.time()
    while True:
        resp = vt_request(url, api_key)
        status = resp["data"]["attributes"]["status"]
        if status == "completed":
            return resp["data"]
        if time.time() - start > timeout:
            raise TimeoutError(f"Analysis {analysis_id} not completed within {timeout}s (last={status})")
        print(f"  status={status} — waiting 15s ...")
        time.sleep(15)


def fetch_report_by_hash(sha256: str, api_key: str) -> dict:
    url = VT_FILE_URL.format(sha256=sha256)
    return vt_request(url, api_key)


def print_report(data: dict, file_hash: str | None = None):
    # data is either analysis.attributes or file.attributes
    attrs = data.get("attributes", data)
    stats = attrs.get("stats") or attrs.get("last_analysis_stats") or {}
    results = attrs.get("results") or attrs.get("last_analysis_results") or {}

    malicious = stats.get("malicious", 0)
    total = sum(stats.values()) if stats else len(results)
    # VT uses 70-73 engines depending on file
    if stats:
        print(f"\nResult: {malicious}/{total} flagged as malicious")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    else:
        print("\nResult: (no stats field)")

    if file_hash:
        print(f"SHA-256: {file_hash}")
        print(f"VT link: https://www.virustotal.com/gui/file/{file_hash}")

    flagged = [(eng, r.get("result") or r.get("category")) for eng, r in results.items() if r.get("category") in ("malicious", "suspicious")]
    if flagged:
        print("\nFlagged engines:")
        for eng, res in sorted(flagged):
            print(f"  {eng}: {res}")
    else:
        print("\nNo engines flagged as malicious/suspicious.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check a file with VirusTotal")
    ap.add_argument("file", nargs="?", help="path to exe to upload (e.g. dist/SRR.exe)")
    ap.add_argument("--hash", dest="hash", help="lookup existing report by SHA-256 instead of uploading")
    ap.add_argument("--apikey", help="VT API key (overrides env/.env)")
    ap.add_argument("--timeout", type=int, default=300, help="poll timeout in seconds (default 300)")
    args = ap.parse_args()

    api_key = load_api_key(args.apikey)
    if not api_key:
        print("ERROR: VT_API_KEY not found. Set it via --apikey, env var, or .env (VT_API_KEY=...).", file=sys.stderr)
        print("Get a free key at https://www.virustotal.com/gui/my-apikey", file=sys.stderr)
        return 2

    if args.hash:
        h = args.hash.strip().lower()
        print(f"Fetching report for {h} ...")
        try:
            resp = fetch_report_by_hash(h, api_key)
            print_report(resp["data"], h)
        except RuntimeError as e:
            print(f"Failed: {e}", file=sys.stderr)
            return 1
        return 0

    if not args.file:
        ap.print_help()
        return 2

    path = Path(args.file)
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    if path.stat().st_size > 32 * 1024 * 1024:
        print("WARNING: free VT API limits uploads to 32 MB — this file may be rejected.", file=sys.stderr)

    h = sha256_of(path)
    print(f"SHA-256: {h}")

    # If VT already knows the file, a hash lookup is cheaper than re-upload.
    # Try it first to save quota.
    try:
        resp = fetch_report_by_hash(h, api_key)
        print("File already known to VT — showing cached report (no quota spent on upload).")
        print_report(resp["data"], h)
        print("\nTip: VT may return a stale report; force re-upload with --hash not set and re-run if needed.")
        return 0
    except RuntimeError as e:
        if "404" not in str(e):
            print(f"Hash lookup failed ({e}), proceeding to upload ...")
        else:
            print("File not yet known to VT — uploading ...")

    try:
        analysis_id = upload_file(path, api_key)
        data = poll_analysis(analysis_id, api_key, timeout=args.timeout)
        print_report(data, h)
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
