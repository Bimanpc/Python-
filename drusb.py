#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI-assisted USB Immunizer (Windows)
- Detect removable drives
- Immunize against autorun malware
- Scrub suspicious files
- Summarize with an LLM (optional)

Dependencies: pywin32 (optional but recommended), requests (for LLM)
Run as Administrator for ACL operations.
"""

import os
import sys
import time
import json
import ctypes
import threading
import traceback
from datetime import datetime
from pathlib import Path

# Optional deps
try:
    import win32api
    import win32file
    import win32con
except Exception:
    win32api = None
    win32file = None
    win32con = None

try:
    import requests
except Exception:
    requests = None

LOG_DIR = Path(os.getenv("USB_IMMUNIZER_LOG", Path.home() / "USB_Immunizer_Logs"))
SCAN_INTERVAL_SEC = 3
LLM_ENABLED = bool(os.getenv("LLM_API_KEY"))
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # adjust to your provider
DRY_RUN = bool(os.getenv("USB_IMMUNIZER_DRYRUN"))  # set any value to enable

SUSPICIOUS_NAMES = {
    "autorun.inf",
    "RECYCLER",
    "System Volume Information",
}

SUSPICIOUS_EXT = {".lnk", ".vbs", ".js", ".jse", ".scr", ".pif", ".bat", ".cmd", ".com", ".exe"}

DOUBLE_EXT_RISK = {".jpg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".mp3", ".mp4"}

# ---------- Admin checks ----------

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def require_admin():
    if not is_admin():
        print("[!] Please run this script as Administrator for full protection.")
        print("    Some operations (ACL immunization) will be skipped.")
        time.sleep(1)

# ---------- Logging ----------

def ensure_log_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

def log_event(drive, level, message, data=None):
    ensure_log_dir()
    ts = datetime.utcnow().isoformat()
    entry = {"ts": ts, "drive": drive, "level": level, "message": message, "data": data or {}}
    print(f"[{level}] {drive}: {message}")
    try:
        with open(LOG_DIR / "usb_immunizer.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

# ---------- Drive detection ----------

def list_removable_drives():
    drives = []
    if win32api:
        try:
            for drive in win32api.GetLogicalDriveStrings().split("\x00"):
                if not drive:
                    continue
                t = win32file.GetDriveType(drive)
                # DRIVE_REMOVABLE = 2, DRIVE_FIXED = 3
                if t == win32con.DRIVE_REMOVABLE:
                    drives.append(drive)
        except Exception:
            # Fallback to simple enumeration
            drives = [f"{chr(c)}:\\" for c in range(68, 91) if Path(f"{chr(c)}:\\").exists()]  # D:..Z:
    else:
        # Fallback when pywin32 missing: heuristic
        drives = [f"{chr(c)}:\\" for c in range(68, 91) if Path(f"{chr(c)}:\\").exists()]
    return drives

# ---------- Immunization ----------

def create_locked_autorun_dir(root: Path):
    """
    Create 'autorun.inf' as a directory with restricted ACL to block malware.
    """
    target = root / "autorun.inf"
    try:
        if target.exists():
            if target.is_file():
                # Replace file with directory
                if not DRY_RUN:
                    target.unlink(missing_ok=True)
                log_event(str(root), "INFO", "Removed existing autorun.inf file")
        if not target.exists():
            if not DRY_RUN:
                target.mkdir()
            log_event(str(root), "INFO", "Created autorun.inf directory")

        # Hide and set system attributes
        if win32api and not DRY_RUN:
            win32api.SetFileAttributes(str(target), win32con.FILE_ATTRIBUTE_SYSTEM | win32con.FILE_ATTRIBUTE_HIDDEN)

        # Tighten ACLs if admin
        if is_admin():
            try:
                if not DRY_RUN:
                    # Deny write to Everyone while preserving read for owner/admins.
                    # Minimalistic ACE via icacls for simplicity.
                    os.system(f'icacls "{target}" /inheritance:d >nul 2>nul')
                    os.system(f'icacls "{target}" /grant:r "Administrators:(OI)(CI)(F)" >nul 2>nul')
                    os.system(f'icacls "{target}" /grant:r "SYSTEM:(OI)(CI)(F)" >nul 2>nul')
                    os.system(f'icacls "{target}" /deny "*S-1-1-0":(W,D,WDAC) >nul 2>nul')  # Everyone SID
                log_event(str(root), "INFO", "Applied restrictive ACLs to autorun.inf directory")
            except Exception as e:
                log_event(str(root), "WARN", f"ACL application failed: {e}")
        else:
            log_event(str(root), "WARN", "Skipped ACL hardening (admin required)")
    except Exception as e:
        log_event(str(root), "ERROR", f"Immunization failed: {e}", {"trace": traceback.format_exc()})

# ---------- Scrubbing & heuristics ----------

def is_hidden_or_system(p: Path) -> bool:
    if not win32api:
        return False
    try:
        attrs = win32api.GetFileAttributes(str(p))
        return bool(attrs & (win32con.FILE_ATTRIBUTE_HIDDEN | win32con.FILE_ATTRIBUTE_SYSTEM))
    except Exception:
        return False

def looks_double_ext(name: str) -> bool:
    lower = name.lower()
    parts = lower.split(".")
    if len(parts) >= 3:
        last = "." + parts[-1]
        prev = "." + parts[-2]
        if last in SUSPICIOUS_EXT and prev in DOUBLE_EXT_RISK:
            return True
    return False

def scrub_drive(root: Path):
    """
    Remove obviously suspicious files and collect flags.
    """
    flags = []
    removed = []

    def flag(label, path, extra=None):
        item = {"label": label, "path": str(path), "extra": extra or {}}
        flags.append(item)
        log_event(str(root), "INFO", f"Flagged: {label} => {path}", item)

    # 1) Remove root autorun.inf file
    autorun_file = root / "autorun.inf"
    if autorun_file.exists() and autorun_file.is_file():
        flag("autorun.inf file in root", autorun_file)
        if not DRY_RUN:
            try:
                os.chmod(autorun_file, 0o600)
                autorun_file.unlink()
                removed.append(str(autorun_file))
                log_event(str(root), "INFO", "Removed autorun.inf file")
            except Exception as e:
                log_event(str(root), "WARN", f"Failed to remove autorun.inf: {e}")

    # 2) Suspicious names/dirs
    for name in SUSPICIOUS_NAMES:
        p = root / name
        if p.exists():
            if p.is_file():
                flag(f"suspicious file '{name}'", p)
                if not DRY_RUN:
                    try:
                        os.chmod(p, 0o600)
                        p.unlink()
                        removed.append(str(p))
                    except Exception as e:
                        log_event(str(root), "WARN", f"Failed to remove {name}: {e}")
            else:
                flag(f"suspicious directory '{name}'", p)
                # Avoid deleting system dirs by default; record only
                # If you insist on removal: implement safe recursive delete with ownership checks.

    # 3) Root executables and hidden/system files
    try:
        for entry in root.iterdir():
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in SUSPICIOUS_EXT:
                    flag("executable in root", entry, {"ext": ext})
                    if is_hidden_or_system(entry):
                        flag("hidden/system attribute", entry)
                if looks_double_ext(entry.name):
                    flag("double-extension trick", entry)
                # Optional: remove .lnk in root unless known good
                if ext == ".lnk":
                    flag("shortcut lure", entry)
                    if not DRY_RUN:
                        try:
                            os.chmod(entry, 0o600)
                            entry.unlink()
                            removed.append(str(entry))
                        except Exception as e:
                            log_event(str(root), "WARN", f"Failed to remove {entry.name}: {e}")
    except Exception as e:
        log_event(str(root), "WARN", f"Root scan error: {e}")

    return flags, removed

# ---------- LLM integration ----------

def call_llm_summary(flags):
    if not LLM_ENABLED or requests is None:
        return None, "LLM disabled or requests missing"

    try:
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            return None, "LLM API key not set"
        prompt = (
            "You are analyzing potentially malicious USB contents found by a simple heuristic scanner.\n"
            "Summarize risks and suggest cautious actions WITHOUT recommending risky steps. "
            "Avoid technical overreach; be specific to items. Input JSON:\n"
            + json.dumps(flags, ensure_ascii=False, indent=2)
        )

        # Example: OpenAI-style JSON endpoint (adjust to your provider)
        url = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are a cautious security assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI-style extraction
        summary = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return summary, None
    except Exception as e:
        return None, f"LLM call failed: {e}"

# ---------- Main workflow ----------

def process_drive(drive: str):
    root = Path(drive)
    log_event(drive, "INFO", "Processing drive")
    create_locked_autorun_dir(root)
    flags, removed = scrub_drive(root)
    summary, err = call_llm_summary(flags)

    result = {
        "drive": drive,
        "flags": flags,
        "removed": removed,
        "llm_summary": summary,
        "llm_error": err,
    }

    # Save per-drive report
    ensure_log_dir()
    report_path = LOG_DIR / f"report_{drive.replace(':', '')}_{int(time.time())}.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log_event(drive, "INFO", f"Saved report: {report_path}")
    except Exception as e:
        log_event(drive, "WARN", f"Failed to save report: {e}")

def monitor_loop():
    seen = set()
    log_event("-", "INFO", "Starting USB immunizer")
    require_admin()
    while True:
        try:
            current = set(list_removable_drives())
            # New drives
            for d in sorted(current - seen):
                # Debounce: give Windows a moment to mount
                time.sleep(1.0)
                threading.Thread(target=process_drive, args=(d,), daemon=True).start()
            seen = current
            time.sleep(SCAN_INTERVAL_SEC)
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            log_event("-", "ERROR", f"Monitor error: {e}", {"trace": traceback.format_exc()})
            time.sleep(5)

if __name__ == "__main__":
    monitor_loop()
