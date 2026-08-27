"""Update checker for SRR — stdlib only, no new dependencies."""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from version import __version__

LATEST_RELEASE_URL = "https://github.com/Mefgner/Smart-Refresh-Rate/releases/latest"
RELEASES_API_URL = "https://api.github.com/repos/Mefgner/Smart-Refresh-Rate/releases/latest"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse dotted version into numeric tuple, ignoring leading 'v' and suffixes."""
    v = v.strip()
    if v.lower().startswith("v"):
        v = v[1:]
    # ignore prerelease/build suffixes after '-'
    v = v.split("-")[0]
    parts = v.split(".")
    nums: list[int] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # extract leading numeric characters
        num_str = ""
        for ch in p:
            if ch.isdigit():
                num_str += ch
            else:
                break
        if num_str:
            try:
                nums.append(int(num_str))
            except ValueError:
                continue
        else:
            # no leading digits — treat as 0? skip
            continue
    return tuple(nums)


def _is_newer(latest: str, current: str) -> bool:
    """Return True if latest version is numerically newer than current."""
    latest_t = _parse_version(latest)
    current_t = _parse_version(current)
    max_len = max(len(latest_t), len(current_t))
    # pad shorter with zeros for fair compare (e.g. 1.2 == 1.2.0)
    latest_padded = latest_t + (0,) * (max_len - len(latest_t))
    current_padded = current_t + (0,) * (max_len - len(current_t))
    return latest_padded > current_padded


def _fetch_latest_tag_sync() -> Optional[str]:
    """Synchronous fetch of latest tag_name from GitHub API; returns stripped version or None."""
    req = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "SRR-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            tag = data.get("tag_name")
            if not isinstance(tag, str):
                return None
            tag = tag.strip()
            if tag.lower().startswith("v"):
                tag = tag[1:]
            return tag.strip() or None
    except Exception as e:
        logging.warning(f"update check failed: {e}")
        return None


async def check_for_updates() -> Optional[str]:
    """Return latest version string if newer than __version__, else None. Never raises."""
    try:
        latest = await asyncio.to_thread(_fetch_latest_tag_sync)
    except Exception as e:
        logging.warning(f"update check failed: {e}")
        return None
    if latest is None:
        return None
    try:
        if _is_newer(latest, __version__):
            return latest
    except Exception as e:
        logging.warning(f"version compare failed: {e}")
        return None
    return None
