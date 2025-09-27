# mpc_ai_controller.py
import os
import time
import json
import argparse
from typing import Optional, Dict, Any

import requests
from flask import Flask, request, jsonify

# LLM (OpenAI SDK)
from openai import OpenAI

# Windows UI fallback
from pywinauto import Application, keyboard
from pywinauto.findwindows import find_window


# -----------------------------
# Config
# -----------------------------
MPC_HOST = os.environ.get("MPC_HOST", "127.0.0.1")
MPC_PORT = int(os.environ.get("MPC_PORT", "13579"))
MPC_BASE = f"http://{MPC_HOST}:{MPC_PORT}"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Web command mapping for MPC-HC
# Reference: MPC-HC exposes wm_command via /command.html?wm_command={id}
# These are common actions; you can extend as needed.
WM_COMMANDS = {
    "play_pause": 889,    # Play/Pause
    "stop": 890,          # Stop
    "next": 922,          # Next file
    "prev": 921,          # Previous file
    "mute": 909,          # Mute
    "fullscreen": 830,    # Toggle fullscreen
    "volume_up": 907,     # Volume up
    "volume_down": 908,   # Volume down
    "audio_cycle": 952,   # Next audio track
    "sub_cycle": 953,     # Next subtitle track
    "rate_inc": 897,      # Increase playback rate
    "rate_dec": 898,      # Decrease playback rate
    "normal_rate": 899,   # Reset rate to normal
}

# -----------------------------
# LLM Intent Parsing
# -----------------------------
SYSTEM_PROMPT = """You are an intent parser for media control.
Extract a single JSON object with fields:
- action: one of [play_pause, stop, next, prev, seek_forward, seek_backward, volume_up, volume_down, mute, fullscreen, audio_cycle, sub_cycle, rate_inc, rate_dec, normal_rate]
- value: optional number (seconds for seek, units for volume steps, rate factor for speed)
- notes: brief string

Infer reasonable defaults (e.g., 10 seconds for seek if not specified).
Only output JSON. No extra text.
Examples:
"skip ahead 30" -> {"action":"seek_forward","value":30,"notes":"seek forward"}
"back 10 seconds" -> {"action":"seek_backward","value":10,"notes":"seek backward"}
"pause" -> {"action":"play_pause","notes":"toggle play/pause"}
"mute" -> {"action":"mute","notes":"toggle mute"}
"speed up" -> {"action":"rate_inc","value":0.1,"notes":"increase playback rate"}
"normal speed" -> {"action":"normal_rate","notes":"reset rate"}
"""

def parse_intent_with_llm(text: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        # Minimal rule-based fallback if no API key present
        return simple_rule_intent(text)

    client = OpenAI(api_key=OPENAI_API_KEY)
    res = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    )
    # Extract the JSON string from the text output
    content = res.output_text.strip()
    try:
        return json.loads(content)
    except Exception:
        # If parsing fails, try rule-based
        return simple_rule_intent(text)


def simple_rule_intent(text: str) -> Dict[str, Any]:
    t = text.lower().strip()
    # Defaults
    intent = {"action": "play_pause", "notes": "fallback toggle"}

    # Play/Pause/Stop
    if any(x in t for x in ["pause", "play/pause", "resume", "play"]):
        intent["action"] = "play_pause"
    if "stop" in t:
        intent["action"] = "stop"

    # Next/Prev
    if "next" in t:
        intent["action"] = "next"
    if "previous" in t or "prev" in t or "back to previous" in t:
        intent["action"] = "prev"

    # Seek
    if "skip" in t or "seek" in t or "forward" in t:
        intent["action"] = "seek_forward"
        intent["value"] = extract_seconds(t) or 10
    if "back" in t or "rewind" in t:
        intent["action"] = "seek_backward"
        intent["value"] = extract_seconds(t) or 10

    # Volume
    if "volume up" in t or "louder" in t or "increase volume" in t:
        intent["action"] = "volume_up"
        intent["value"] = 1
    if "volume down" in t or "quieter" in t or "decrease volume" in t:
        intent["action"] = "volume_down"
        intent["value"] = 1
    if "mute" in t or "unmute" in t:
        intent["action"] = "mute"

    # Fullscreen
    if "fullscreen" in t or "full screen" in t or "windowed" in t:
        intent["action"] = "fullscreen"

    # Tracks
    if "subtitle" in t and ("next" in t or "cycle" in t or "change" in t):
        intent["action"] = "sub_cycle"
    if "audio" in t and ("next" in t or "cycle" in t or "change" in t):
        intent["action"] = "audio_cycle"

    # Speed
    if "speed up" in t or "faster" in t or "increase speed" in t:
        intent["action"] = "rate_inc"
        intent["value"] = 0.1
    if "slow down" in t or "decrease speed" in t or "slower" in t:
        intent["action"] = "rate_dec"
        intent["value"] = 0.1
    if "normal speed" in t or "reset speed" in t:
        intent["action"] = "normal_rate"

    return intent


def extract_seconds(text: str) -> Optional[int]:
    import re
    m = re.search(r"(\d+)\s*(sec|secs|seconds|s)?", text)
    if m:
        try:
            return int(m.group(1))
        except:
            return None
    return None


# -----------------------------
# MPC Controller (Web + UI)
# -----------------------------
class MPCController:
    def __init__(self):
        self.web_available = self._check_web()

    def _check_web(self) -> bool:
        try:
            r = requests.get(f"{MPC_BASE}/variables.html", timeout=0.5)
            return r.status_code == 200
        except Exception:
            return False

    # ---- Web API path ----
    def _wm(self, cmd_id: int):
        return requests.get(f"{MPC_BASE}/command.html", params={"wm_command": cmd_id}, timeout=1)

    def play_pause(self):
        if self.web_available:
            self._wm(WM_COMMANDS["play_pause"])
        else:
            self._ui_key("{SPACE}")

    def stop(self):
        if self.web_available:
            self._wm(WM_COMMANDS["stop"])
        else:
            self._ui_key("s")

    def next(self):
        if self.web_available:
            self._wm(WM_COMMANDS["next"])
        else:
            self._ui_key("{PGDN}")

    def prev(self):
        if self.web_available:
            self._wm(WM_COMMANDS["prev"])
        else:
            self._ui_key("{PGUP}")

    def mute(self):
        if self.web_available:
            self._wm(WM_COMMANDS["mute"])
        else:
            self._ui_key("m")

    def fullscreen(self):
        if self.web_available:
            self._wm(WM_COMMANDS["fullscreen"])
        else:
            self._ui_key("f")

    def volume_up(self, steps: int = 1):
        if self.web_available:
            for _ in range(max(1, steps)):
                self._wm(WM_COMMANDS["volume_up"])
        else:
            for _ in range(max(1, steps)):
                self._ui_key("{UP}")

    def volume_down(self, steps: int = 1):
        if self.web_available:
            for _ in range(max(1, steps)):
                self._wm(WM_COMMANDS["volume_down"])
        else:
            for _ in range(max(1, steps)):
                self._ui_key("{DOWN}")

    def seek_forward(self, seconds: int = 10):
        if self.web_available:
            # Web interface supports relative seek via /jump.html?time=+N
            try:
                requests.get(f"{MPC_BASE}/jump.html", params={"time": f"+{max(1, seconds)}"}, timeout=1)
            except Exception:
                # fallback large step via right arrow repeats
                repeats = max(1, seconds // 5)
                for _ in range(repeats):
                    self._ui_key("{RIGHT}")
        else:
            repeats = max(1, seconds // 5)
            for _ in range(repeats):
                self._ui_key("{RIGHT}")

    def seek_backward(self, seconds: int = 10):
        if self.web_available:
            try:
                requests.get(f"{MPC_BASE}/jump.html", params={"time": f"-{max(1, seconds)}"}, timeout=1)
            except Exception:
                repeats = max(1, seconds // 5)
                for _ in range(repeats):
                    self._ui_key("{LEFT}")
        else:
            repeats = max(1, seconds // 5)
            for _ in range(repeats):
                self._ui_key("{LEFT}")

    def audio_cycle(self):
        if self.web_available:
            self._wm(WM_COMMANDS["audio_cycle"])
        else:
            self._ui_key("a")

    def sub_cycle(self):
        if self.web_available:
            self._wm(WM_COMMANDS["sub_cycle"])
        else:
            self._ui_key("s")

    def rate_inc(self, delta: float = 0.1):
        if self.web_available:
            self._wm(WM_COMMANDS["rate_inc"])
        else:
            # MPC-HC default: Ctrl+Up increases rate
            self._ui_key("^({UP})")

    def rate_dec(self, delta: float = 0.1):
        if self.web_available:
            self._wm(WM_COMMANDS["rate_dec"])
        else:
            # MPC-HC default: Ctrl+Down decreases rate
            self._ui_key("^({DOWN})")

    def normal_rate(self):
        if self.web_available:
            self._wm(WM_COMMANDS["normal_rate"])
        else:
            # MPC-HC default: Backspace resets rate
            self._ui_key("{BACKSPACE}")

    # ---- UI path ----
    def _ui_key(self, key: str):
        try:
            hwnd = find_window(title_re=r".*Media Player Classic.*")
            app = Application(backend="uia").connect(handle=hwnd)
            keyboard.send_keys(key, with_spaces=True)
        except Exception:
            # If MPC window not found, try launching or just ignore
            pass


# -----------------------------
# Orchestration
# -----------------------------
def handle_text_command(text: str) -> Dict[str, Any]:
    intent = parse_intent_with_llm(text)
    ctrl = MPCController()
    action = intent.get("action")
    value = intent.get("value")

    # Dispatch
    if action == "play_pause":
        ctrl.play_pause()
    elif action == "stop":
        ctrl.stop()
    elif action == "next":
        ctrl.next()
    elif action == "prev":
        ctrl.prev()
    elif action == "mute":
        ctrl.mute()
    elif action == "fullscreen":
        ctrl.fullscreen()
    elif action == "volume_up":
        ctrl.volume_up(int(value or 1))
    elif action == "volume_down":
        ctrl.volume_down(int(value or 1))
    elif action == "seek_forward":
        ctrl.seek_forward(int(value or 10))
    elif action == "seek_backward":
        ctrl.seek_backward(int(value or 10))
    elif action == "audio_cycle":
        ctrl.audio_cycle()
    elif action == "sub_cycle":
        ctrl.sub_cycle()
    elif action == "rate_inc":
        ctrl.rate_inc(float(value or 0.1))
    elif action == "rate_dec":
        ctrl.rate_dec(float(value or 0.1))
    elif action == "normal_rate":
        ctrl.normal_rate()
    else:
        # Fallback
        ctrl.play_pause()

    return {"ok": True, "intent": intent, "web": MPCController().web_available}


# -----------------------------
# Flask server
# -----------------------------
app = Flask(__name__)

@app.route("/command", methods=["POST"])
def command():
    data = request.get_json(force=True)
    text = data.get("text") or ""
    if not text.strip():
        return jsonify({"ok": False, "error": "Empty text"}), 400
    result = handle_text_command(text)
    return jsonify(result)


# -----------------------------
# CLI mode
# -----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run in interactive CLI mode")
    parser.add_argument("--host", default="127.0.0.1", help="Flask host")
    parser.add_argument("--port", type=int, default=5000, help="Flask port")
    args = parser.parse_args()

    if args.cli:
        print("MPC AI Controller (CLI). Type commands like 'pause', 'skip 30', 'mute', 'speed up', 'next subtitle'. Ctrl+C to quit.")
        while True:
            try:
                text = input("> ").strip()
                if not text:
                    continue
                result = handle_text_command(text)
                print("Intent:", result["intent"])
            except KeyboardInterrupt:
                break
    else:
        print(f"Starting server at http://{args.host}:{args.port}")
        app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
