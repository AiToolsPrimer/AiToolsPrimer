"""macOS notifications (no-op elsewhere)."""
from __future__ import annotations

import platform
import shutil
import subprocess


def notify(title: str, text: str, sound: bool = False) -> bool:
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        return False
    safe_t, safe_x = title.replace('"', "'"), text.replace('"', "'")[:200]
    script = f'display notification "{safe_x}" with title "{safe_t}"' + (' sound name "Glass"' if sound else "")
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False
