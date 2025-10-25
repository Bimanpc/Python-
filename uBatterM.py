#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI LLM Battery Laptop Manager (Tkinter, cross-platform)
- Battery/status: psutil
- Actions: brightness, Wi-Fi toggle (best-effort, platform-aware)
- AI panel: backend_contract_llm() stub to integrate any LLM endpoint
- Logging: rotating log, periodic sampling
"""

import os
import sys
import time
import platform
import subprocess
import threading
from datetime import datetime
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, messagebox

# Optional deps: psutil (pip install psutil)
try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "AI Battery Manager"
SAMPLE_INTERVAL_SEC = 10
LOG_MAX_LINES = 5000

# -------------- Backend contract for AI (wire your LLM here) --------------

def backend_contract_llm(context: dict, prompt: str) -> str:
    """
    Replace with your LLM call.
    Required contract:
      - Input:
          context: {
            'battery_percent': float or None,
            'power_plugged': bool or None,
            'secs_left': int or None,
            'cpu_percent': float or None,
            'platform': str,
            'timestamp': str
          }
          prompt: user text
      - Output: plain string response
    """
    # Stubbed "smart" suggestions; replace with real LLM request
    bp = context.get('battery_percent')
    plugged = context.get('power_plugged')
    cpu = context.get('cpu_percent')
    secs_left = context.get('secs_left')

    def fmt_time(s):
        if s is None or s < 0:
            return "unknown"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"

    status = []
    if bp is not None:
        status.append(f"Battery: {bp:.0f}%")
    if plugged is not None:
        status.append("Plugged" if plugged else "On battery")
    if cpu is not None:
        status.append(f"CPU: {cpu:.0f}%")
    status.append(f"Time left: {fmt_time(secs_left)}")

    baseline = " | ".join(status)
    advice = []
    if plugged is False and (bp is not None and bp < 30):
        advice.append("Lower brightness and disable Wi‑Fi if not needed.")
    if cpu and cpu > 50:
        advice.append("High CPU detected; close heavy apps or pause background tasks.")
    if plugged:
        advice.append("Since you’re plugged in, enable battery charge limit if supported to prolong lifespan.")
    if not advice:
        advice.append("You’re in good shape. Keep apps minimal and brightness moderate for best endurance.")

    # Simple prompt-aware reply
    reply = f"{baseline}\n\nPrompt: {prompt}\n\nSuggestions:\n- " + "\n- ".join(advice)
    return reply

# -------------- Utilities and platform-aware actions --------------

def get_battery_info():
    if psutil is None:
        return None, None, None
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return None, None, None
        return batt.percent, batt.power_plugged, batt.secsleft
    except Exception:
        return None, None, None

def get_cpu_percent():
    if psutil is None:
        return None
    try:
        # psutil.cpu_percent(interval=0.2) blocks briefly; 0 for non-blocking
        return psutil.cpu_percent(interval=0.0)
    except Exception:
        return None

def dim_brightness_best_effort():
    """
    Best-effort brightness dim:
      - Windows: monitor brightness via WMI (requires admin) fallback to no-op
      - macOS: uses 'brightness' utility if present (brew install brightness)
      - Linux: tries xbacklight/light, else sysfs (requires permissions)
    Returns (success:bool, message:str)
    """
    os_name = platform.system().lower()

    try:
        if os_name == "windows":
            # Try WMI via powershell: set brightness to 30%
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,30) | Out-Null"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True, "Brightness set to ~30% (Windows)."
            return False, "Couldn’t change brightness (Windows). Try running as admin."

        elif os_name == "darwin":
            # macOS: brightness tool
            if shutil_which("brightness"):
                result = subprocess.run(["brightness", "0.3"])
                if result.returncode == 0:
                    return True, "Brightness set to 30% (macOS)."
                return False, "Failed to change brightness (macOS)."
            return False, "Install 'brightness' utility (brew install brightness)."

        else:
            # Linux: try light, xbacklight, then sysfs
            if shutil_which("light"):
                r = subprocess.run(["light", "-S", "30"])
                if r.returncode == 0:
                    return True, "Brightness set to 30% using light."
            if shutil_which("xbacklight"):
                r = subprocess.run(["xbacklight", "-set", "30"])
                if r.returncode == 0:
                    return True, "Brightness set to 30% using xbacklight."
            # sysfs
            paths = [
                "/sys/class/backlight/intel_backlight",
                "/sys/class/backlight/acpi_video0",
                "/sys/class/backlight/amdgpu_bl0",
            ]
            for p in paths:
                try:
                    maxp = os.path.join(p, "max_brightness")
                    curp = os.path.join(p, "brightness")
                    if os.path.exists(maxp) and os.path.exists(curp):
                        with open(maxp, "r") as f:
                            maxb = int(f.read().strip())
                        target = max(1, int(maxb * 0.3))
                        with open(curp, "w") as f:
                            f.write(str(target))
                        return True, "Brightness set to ~30% via sysfs."
                except Exception:
                    continue
            return False, "Couldn’t adjust brightness (Linux). Try running with proper permissions."

    except Exception as e:
        return False, f"Error: {e}"

def shutil_which(cmd):
    # small helper to avoid importing shutil
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts = [""] if platform.system().lower() != "windows" else os.environ.get("PATHEXT", ".EXE;.BAT;.CMD").split(";")
    for d in paths:
        for ext in exts:
            candidate = os.path.join(d, cmd + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None

def toggle_wifi_best_effort():
    """
    Toggle Wi‑Fi best-effort:
      - Windows: netsh to disable/enable WLAN interface
      - macOS: networksetup on Wi‑Fi
      - Linux: nmcli radio wifi off/on (requires NetworkManager)
    Returns (success:bool, message:str)
    """
    os_name = platform.system().lower()
    try:
        if os_name == "windows":
            # Query interfaces
            q = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True)
            if q.returncode != 0:
                return False, "Failed to query Wi‑Fi interfaces."
            text = q.stdout.lower()
            # Try to toggle by setting hostednetwork or interface state is non-trivial; provide quick off
            off = subprocess.run(["netsh", "interface", "set", "interface", "name=\"Wi-Fi\"", "admin=disabled"], capture_output=True, text=True)
            if off.returncode == 0:
                return True, "Wi‑Fi disabled (Windows). Run again to re-enable."
            # Fallback: try WLAN service
            off2 = subprocess.run(["netsh", "wlan", "disconnect"], capture_output=True, text=True)
            if off2.returncode == 0:
                return True, "Wi‑Fi disconnected (Windows)."
            return False, "Couldn’t toggle Wi‑Fi (Windows). Try as admin."

        elif os_name == "darwin":
            # macOS
            if shutil_which("networksetup"):
                off = subprocess.run(["networksetup", "-setairportpower", "Wi-Fi", "off"])
                if off.returncode == 0:
                    return True, "Wi‑Fi turned off (macOS). Run again to turn on."
                return False, "Failed to toggle Wi‑Fi (macOS)."
            return False, "networksetup not found (macOS)."

        else:
            # Linux
            if shutil_which("nmcli"):
                off = subprocess.run(["nmcli", "radio", "wifi", "off"])
                if off.returncode == 0:
                    return True, "Wi‑Fi off via nmcli. Run again to turn on."
                return False, "Failed to toggle Wi‑Fi with nmcli."
            return False, "nmcli not available. Try your distro’s network tool."

    except Exception as e:
        return False, f"Error: {e}"

# -------------- App UI and logic --------------

class BatteryManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_NAME)
        root.geometry("900x600")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.running = True

        self.sample_queue = Queue()
        self.log_lines = []

        self._build_ui()
        self._start_sampling_thread()
        self._tick_ui()

    def _build_ui(self):
        # Top frame: status
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        self.lbl_battery = ttk.Label(top, text="Battery: -")
        self.lbl_power = ttk.Label(top, text="Power: -")
        self.lbl_timeleft = ttk.Label(top, text="Time left: -")
        self.lbl_cpu = ttk.Label(top, text="CPU: -")

        self.lbl_battery.pack(side=tk.LEFT, padx=8)
        self.lbl_power.pack(side=tk.LEFT, padx=8)
        self.lbl_timeleft.pack(side=tk.LEFT, padx=8)
        self.lbl_cpu.pack(side=tk.RIGHT, padx=8)

        # Middle: progress and actions
        mid = ttk.Frame(self.root, padding=10)
        mid.pack(fill=tk.X)

        self.pb_battery = ttk.Progressbar(mid, orient="horizontal", length=300, mode="determinate", maximum=100)
        self.pb_battery.pack(side=tk.LEFT, padx=8)

        actions = ttk.Frame(mid)
        actions.pack(side=tk.RIGHT)

        self.btn_dim = ttk.Button(actions, text="Dim brightness", command=self.on_dim)
        self.btn_wifi = ttk.Button(actions, text="Toggle Wi‑Fi", command=self.on_wifi)
        self.btn_tips = ttk.Button(actions, text="Quick tips", command=self.on_tips)

        self.btn_dim.grid(row=0, column=0, padx=5, pady=2)
        self.btn_wifi.grid(row=0, column=1, padx=5, pady=2)
        self.btn_tips.grid(row=0, column=2, padx=5, pady=2)

        # Notebook: Logs and AI
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True)

        # Logs tab
        self.txt_logs = tk.Text(nb, wrap="word", height=12)
        self.txt_logs.configure(state="disabled")
        nb.add(self.txt_logs, text="Logs")

        # AI tab
        ai_frame = ttk.Frame(nb, padding=10)
        nb.add(ai_frame, text="AI Assistant")

        self.txt_context = tk.Text(ai_frame, wrap="word", height=10)
        self.txt_context.insert("1.0", "Context will auto-fill with current system status.\nYou can edit before sending.")
        self.txt_context.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=5, pady=5)

        self.txt_prompt = tk.Text(ai_frame, wrap="word", height=5)
        self.txt_prompt.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=5, pady=5)

        self.btn_send = ttk.Button(ai_frame, text="Ask AI", command=self.on_ask_ai)
        self.btn_send.grid(row=2, column=0, sticky="w", padx=5, pady=5)

        self.txt_reply = tk.Text(ai_frame, wrap="word", height=12)
        self.txt_reply.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=5, pady=5)

        # Layout weights
        ai_frame.rowconfigure(0, weight=1)
        ai_frame.rowconfigure(1, weight=1)
        ai_frame.rowconfigure(3, weight=2)
        ai_frame.columnconfigure(0, weight=1)
        ai_frame.columnconfigure(1, weight=1)
        ai_frame.columnconfigure(2, weight=1)

    # ---------- Event handlers ----------

    def on_dim(self):
        ok, msg = dim_brightness_best_effort()
        self._append_log(f"[ACTION] Dim brightness: {msg}")
        if not ok:
            messagebox.showinfo(APP_NAME, msg)

    def on_wifi(self):
        ok, msg = toggle_wifi_best_effort()
        self._append_log(f"[ACTION] Toggle Wi‑Fi: {msg}")
        if not ok:
            messagebox.showinfo(APP_NAME, msg)

    def on_tips(self):
        bp, plugged, secs = get_battery_info()
        cpu = get_cpu_percent()
        tips = []

        if plugged is False:
            tips.append("Lower brightness and disable keyboard backlight.")
        if bp is not None and bp < 25:
            tips.append("Enable battery saver mode and close heavy apps.")
        if cpu is not None and cpu > 50:
            tips.append("High CPU: pause background syncs and builds.")
        tips.append("Use dark theme and reduce screen refresh rate if available.")

        text = "Quick battery tips:\n- " + "\n- ".join(tips)
        self._append_log("[TIPS]\n" + text)
        messagebox.showinfo(APP_NAME, text)

    def on_ask_ai(self):
        ctx = self._current_context()
        user_prompt = self.txt_prompt.get("1.0", "end").strip()
        if not user_prompt:
            messagebox.showinfo(APP_NAME, "Write a prompt first.")
            return

        # Auto-fill context panel
        self._update_context_view(ctx)

        # Run AI in a thread to keep UI responsive
        def worker():
            try:
                reply = backend_contract_llm(ctx, user_prompt)
                self.root.after(0, lambda: self._set_reply(reply))
                self._append_log("[AI] Prompt sent.")
            except Exception as e:
                self.root.after(0, lambda: self._set_reply(f"Error: {e}"))
                self._append_log(f"[AI] Error: {e}")

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Sampling and UI updates ----------

    def _start_sampling_thread(self):
        def sampler():
            while self.running:
                bp, plugged, secs = get_battery_info()
                cpu = get_cpu_percent()
                self.sample_queue.put({
                    "ts": time.time(),
                    "battery_percent": bp,
                    "power_plugged": plugged,
                    "secs_left": secs,
                    "cpu_percent": cpu
                })
                time.sleep(SAMPLE_INTERVAL_SEC)
        threading.Thread(target=sampler, daemon=True).start()

    def _tick_ui(self):
        # Drain queue
        try:
            while True:
                item = self.sample_queue.get_nowait()
                self._apply_sample(item)
        except Empty:
            pass

        # Schedule next UI tick
        if self.running:
            self.root.after(500, self._tick_ui)

    def _apply_sample(self, s):
        bp = s.get("battery_percent")
        plugged = s.get("power_plugged")
        secs = s.get("secs_left")
        cpu = s.get("cpu_percent")

        # Update labels
        self.lbl_battery.configure(text=f"Battery: {bp:.0f}%" if bp is not None else "Battery: -")
        self.lbl_power.configure(text=f"Power: {'Plugged' if plugged else 'Battery' if plugged is not None else '-'}")
        self.lbl_timeleft.configure(text=f"Time left: {self._fmt_secs(secs)}")
        self.lbl_cpu.configure(text=f"CPU: {cpu:.0f}%" if cpu is not None else "CPU: -")

        # Update progress bar
        if bp is not None:
            self.pb_battery["value"] = float(bp)
        else:
            self.pb_battery["value"] = 0

        # Log sample
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append_log(f"[{ts}] Battery={bp}%, Plugged={plugged}, TimeLeft={self._fmt_secs(secs)}, CPU={cpu}%")

    def _fmt_secs(self, s):
        if s is None or s < 0:
            return "-"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"

    def _current_context(self):
        bp, plugged, secs = get_battery_info()
        cpu = get_cpu_percent()
        return {
            "battery_percent": bp,
            "power_plugged": plugged,
            "secs_left": secs,
            "cpu_percent": cpu,
            "platform": platform.platform(),
            "timestamp": datetime.now().isoformat(timespec="seconds")
        }

    def _update_context_view(self, ctx: dict):
        text = [
            f"Platform: {ctx.get('platform')}",
            f"Timestamp: {ctx.get('timestamp')}",
            f"Battery percent: {ctx.get('battery_percent')}",
            f"Power plugged: {ctx.get('power_plugged')}",
            f"Seconds left: {ctx.get('secs_left')}",
            f"CPU percent: {ctx.get('cpu_percent')}"
        ]
        self.txt_context.delete("1.0", "end")
        self.txt_context.insert("1.0", "\n".join(text))

    def _set_reply(self, text: str):
        self.txt_reply.delete("1.0", "end")
        self.txt_reply.insert("1.0", text)

    def _append_log(self, line: str):
        self.log_lines.append(line)
        if len(self.log_lines) > LOG_MAX_LINES:
            self.log_lines = self.log_lines[-LOG_MAX_LINES:]
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.insert("1.0", "\n".join(self.log_lines))
        self.txt_logs.configure(state="disabled")

    def on_close(self):
        self.running = False
        self.root.destroy()

# -------------- Entry point --------------

def main():
    # Ensure psutil presence hint
    if psutil is None:
        msg = (
            "psutil not found.\n\nInstall:\n  pip install psutil\n\n"
            "Battery and CPU readings require psutil."
        )
        print(msg)
    root = tk.Tk()
    # Prefer native look
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    app = BatteryManagerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
