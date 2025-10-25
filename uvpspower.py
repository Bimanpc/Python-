#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UPS Power Manager with Tkinter + optional LLM insights
- Monitors UPS via NUT (upsc), APCUPSD (apcaccess), or Windows Battery (WMI fallback).
- Provides GUI for status, logs, alerts, and safe shutdown test.
- Optional LLM panel summarizes current power risk and actions via configurable HTTP endpoint.
- Admin-safe: no registry writes; graceful subprocess handling; read-only polling; optional actions guarded.

Dependencies (optional):
- psutil (for graceful shutdown intent and system info) -> pip install psutil
- pywin32 (for WMI fallback on Windows) -> pip install pywin32
- requests (for LLM calls) -> pip install requests

All dependencies are optional; app runs with basic features without them.
"""

import os
import sys
import time
import json
import queue
import threading
import subprocess
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Optional imports
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

try:
    import win32com.client  # type: ignore
except Exception:
    win32com = None

try:
    import requests  # type: ignore
except Exception:
    requests = None


# ------------------------------
# Configuration and thresholds
# ------------------------------

@dataclass
class AppConfig:
    poll_interval_sec: int = 5
    low_battery_threshold_pct: int = 25
    critical_battery_threshold_pct: int = 10
    # NUT/UPS settings
    nut_upsc_cmd: str = "upsc"           # path/name to upsc binary if available
    nut_ups_name: str = "ups"            # e.g., "myups@localhost" or simple "ups"
    # APCUPSD settings
    apcaccess_cmd: str = "apcaccess"     # path/name to apcaccess binary if available
    # LLM settings
    llm_enabled: bool = False
    llm_endpoint: str = ""               # e.g., http://localhost:8000/v1/chat/completions or other
    llm_api_key: str = ""                # optional header auth
    llm_model: str = "local-llm"         # model identifier for your backend
    llm_timeout_sec: int = 8
    # Behavior
    allow_shutdown_actions: bool = False # guard to prevent actual shutdown without explicit enable
    log_capacity: int = 1000


# ------------------------------
# UPS status model
# ------------------------------

@dataclass
class UPSStatus:
    source: str = "unknown"   # nut/apcupsd/wmi/unknown
    on_battery: Optional[bool] = None
    percentage: Optional[float] = None
    runtime_seconds: Optional[int] = None
    voltage_in: Optional[float] = None
    voltage_out: Optional[float] = None
    load_pct: Optional[float] = None
    status_text: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ------------------------------
# Probers for NUT and APCUPSD
# ------------------------------

def try_run(cmd: list[str], timeout: int = 3) -> tuple[int, str, str]:
    """Run subprocess safely, return (rc, stdout, stderr)."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", err or ""
    except Exception as e:
        return -1, "", str(e)


def probe_nut_upsc(cfg: AppConfig) -> Optional[UPSStatus]:
    """Probe UPS via NUT 'upsc <upsname>'."""
    rc, out, err = try_run([cfg.nut_upsc_cmd, cfg.nut_ups_name], timeout=3)
    if rc != 0 or not out.strip():
        return None

    fields = {}
    for line in out.splitlines():
        # Lines like: "battery.charge: 97"
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()

    status = UPSStatus(source="nut", raw=fields, timestamp=time.time())
    # Map common fields
    charge = fields.get("battery.charge")
    if charge:
        try:
            status.percentage = float(charge)
        except:
            pass

    runtime = fields.get("battery.runtime")
    if runtime:
        try:
            status.runtime_seconds = int(float(runtime))
        except:
            pass

    # status.status may be like "OL" (On line), "OB" (On battery)
    st = fields.get("ups.status", fields.get("status"))
    if st:
        status.status_text = st
        if "OB" in st or "DISCHRG" in st:
            status.on_battery = True
        elif "OL" in st or "CHRG" in st:
            status.on_battery = False

    vin = fields.get("input.voltage")
    vout = fields.get("output.voltage")
    load = fields.get("ups.load")
    for val, attr in [(vin, "voltage_in"), (vout, "voltage_out"), (load, "load_pct")]:
        if val:
            try:
                setattr(status, attr, float(val))
            except:
                pass

    return status


def probe_apcaccess(cfg: AppConfig) -> Optional[UPSStatus]:
    """Probe UPS via APCUPSD 'apcaccess'."""
    rc, out, err = try_run([cfg.apcaccess_cmd], timeout=3)
    if rc != 0 or not out.strip():
        return None

    fields = {}
    for line in out.splitlines():
        # Lines like: "STATUS   : ONLINE"
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip()

    status = UPSStatus(source="apcupsd", raw=fields, timestamp=time.time())
    # Battery remaining (BCHARGE : 97.0 Percent)
    bchg = fields.get("bcharge")
    if bchg:
        try:
            status.percentage = float(bchg.split()[0])
        except:
            pass

    # TIMELEFT : 52.1 Minutes
    tleft = fields.get("timeleft")
    if tleft:
        try:
            minutes = float(tleft.split()[0])
            status.runtime_seconds = int(minutes * 60)
        except:
            pass

    # LINEV / OUTPUTV
    linev = fields.get("linev")
    outv = fields.get("outputv")
    if linev:
        try:
            status.voltage_in = float(linev.split()[0])
        except:
            pass
    if outv:
        try:
            status.voltage_out = float(outv.split()[0])
        except:
            pass

    # LOADPCT : 12.0 Percent
    loadpct = fields.get("loadpct")
    if loadpct:
        try:
            status.load_pct = float(loadpct.split()[0])
        except:
            pass

    # STATUS : ONLINE | ONBATT | CHARGING
    st = fields.get("status")
    if st:
        status.status_text = st.upper()
        if "ONBATT" in status.status_text:
            status.on_battery = True
        elif "ONLINE" in status.status_text:
            status.on_battery = False

    return status


def probe_windows_wmi_fallback() -> Optional[UPSStatus]:
    """Fallback using Windows WMI Battery for laptops or HID UPS with battery class."""
    if os.name != "nt" or win32com is None:
        return None

    try:
        wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        svc = wmi.ConnectServer(".", "root\\CIMV2")
        # Win32_Battery may represent UPS battery when drivers expose it as a battery
        batteries = svc.ExecQuery("SELECT * FROM Win32_Battery")
        status = UPSStatus(source="wmi", raw={}, timestamp=time.time())
        if batteries.Count == 0:
            return None

        # Aggregate
        percents = []
        on_batt = None
        for b in batteries:
            if hasattr(b, "EstimatedChargeRemaining"):
                try:
                    percents.append(float(b.EstimatedChargeRemaining))
                except:
                    pass
            # BatteryStatus: 1=Discharging, 2=AC, etc.
            if hasattr(b, "BatteryStatus"):
                try:
                    bs = int(b.BatteryStatus)
                    # 1 Discharging (on battery), 2 AC (online)
                    if bs == 1:
                        on_batt = True
                    elif bs == 2:
                        on_batt = False
                except:
                    pass

        if percents:
            status.percentage = sum(percents) / len(percents)
        status.on_battery = on_batt
        status.status_text = "Discharging" if on_batt else "AC Online"
        return status

    except Exception:
        return None


# ------------------------------
# LLM Insights
# ------------------------------

def build_llm_prompt(ups: UPSStatus, cfg: AppConfig) -> str:
    """Create a concise prompt for the LLM to summarize risk and actions."""
    # Keep it compact and actionable
    data = {
        "source": ups.source,
        "on_battery": ups.on_battery,
        "percentage": ups.percentage,
        "runtime_seconds": ups.runtime_seconds,
        "voltage_in": ups.voltage_in,
        "voltage_out": ups.voltage_out,
        "load_pct": ups.load_pct,
        "status_text": ups.status_text,
        "low_threshold": cfg.low_battery_threshold_pct,
        "critical_threshold": cfg.critical_battery_threshold_pct,
        "timestamp": datetime.fromtimestamp(ups.timestamp).isoformat(),
    }
    return (
        "Analyze UPS status JSON and provide a brief, practical summary with risk level "
        "(Low/Moderate/High/Critical), and 2–3 recommended actions:\n\n"
        f"{json.dumps(data, ensure_ascii=False)}\n\n"
        "Output format:\n"
        "- Risk: <level>\n"
        "- Why: <one sentence>\n"
        "- Actions: <bulleted list>\n"
    )


def call_llm(prompt: str, cfg: AppConfig) -> str:
    """Call an external LLM endpoint in a generic way. Returns text or an empty string."""
    if not cfg.llm_enabled or not cfg.llm_endpoint or requests is None:
        return ""

    try:
        # Example generic JSON schema; adapt to your backend
        payload = {
            "model": cfg.llm_model,
            "messages": [
                {"role": "system", "content": "You are a concise power management assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }
        headers = {"Content-Type": "application/json"}
        if cfg.llm_api_key:
            headers["Authorization"] = f"Bearer {cfg.llm_api_key}"

        resp = requests.post(cfg.llm_endpoint, headers=headers, json=payload, timeout=cfg.llm_timeout_sec)
        resp.raise_for_status()
        data = resp.json()
        # Try standard chat completion shape; fallback to text
        content = ""
        if isinstance(data, dict):
            # Common shapes
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                content = data.get("text", "")
        return content.strip()
    except Exception as e:
        return f"LLM error: {e}"


# ------------------------------
# Poller
# ------------------------------

class UPSMonitor(threading.Thread):
    def __init__(self, cfg: AppConfig, updates: queue.Queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.updates = updates
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            status = self.poll_once()
            if status:
                self.updates.put(status)
            time.sleep(self.cfg.poll_interval_sec)

    def poll_once(self) -> Optional[UPSStatus]:
        # Priority: NUT -> APCUPSD -> WMI -> None
        st = probe_nut_upsc(self.cfg)
        if st is None:
            st = probe_apcaccess(self.cfg)
        if st is None:
            st = probe_windows_wmi_fallback()

        # Enrich status text if empty
        if st is not None and not st.status_text:
            if st.on_battery is True:
                st.status_text = "On battery (discharging)"
            elif st.on_battery is False:
                st.status_text = "AC online (charging/maintaining)"
            else:
                st.status_text = "Unknown"

        return st


# ------------------------------
# GUI
# ------------------------------

class UPSApp(tk.Tk):
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.title("UPS Power Manager")
        self.geometry("900x600")
        self.minsize(800, 520)

        self.cfg = cfg
        self.updates = queue.Queue()
        self.monitor = UPSMonitor(cfg, self.updates)
        self.log_lines: list[str] = []
        self.last_status: Optional[UPSStatus] = None

        self._build_ui()
        self._bind_events()

        self.monitor.start()
        self.after(200, self._drain_updates)

    def _build_ui(self):
        # Top frame: Status
        top = ttk.LabelFrame(self, text="UPS status")
        top.pack(fill="x", padx=10, pady=10)

        grid = ttk.Frame(top)
        grid.pack(fill="x", padx=8, pady=8)

        # Labels
        self.lbl_source = self._labeled_value(grid, "Source", 0)
        self.lbl_on_battery = self._labeled_value(grid, "On battery", 1)
        self.lbl_percentage = self._labeled_value(grid, "Charge (%)", 2)
        self.lbl_runtime = self._labeled_value(grid, "Runtime (s)", 3)
        self.lbl_vin = self._labeled_value(grid, "Input V", 4)
        self.lbl_vout = self._labeled_value(grid, "Output V", 5)
        self.lbl_load = self._labeled_value(grid, "Load (%)", 6)
        self.lbl_status = self._labeled_value(grid, "Status text", 7)

        # Progress and alert banner
        prog_frame = ttk.Frame(top)
        prog_frame.pack(fill="x", padx=8, pady=4)
        self.progress = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate", length=300)
        self.progress.pack(side="left", padx=(0, 8))
        self.alert_label = ttk.Label(prog_frame, text="No alert", foreground="#222")
        self.alert_label.pack(side="left", padx=8)

        # Middle: Controls
        mid = ttk.LabelFrame(self, text="Controls")
        mid.pack(fill="x", padx=10, pady=5)

        btn_frame = ttk.Frame(mid)
        btn_frame.pack(fill="x", padx=8, pady=8)

        self.btn_refresh = ttk.Button(btn_frame, text="Refresh now", command=self._refresh_now)
        self.btn_refresh.pack(side="left", padx=6)

        self.btn_save_log = ttk.Button(btn_frame, text="Save log...", command=self._save_log)
        self.btn_save_log.pack(side="left", padx=6)

        self.btn_shutdown_test = ttk.Button(btn_frame, text="Shutdown test", command=self._shutdown_test)
        self.btn_shutdown_test.pack(side="left", padx=6)

        self.chk_allow_shutdown_var = tk.BooleanVar(value=self.cfg.allow_shutdown_actions)
        self.chk_allow_shutdown = ttk.Checkbutton(btn_frame, text="Enable shutdown actions", variable=self.chk_allow_shutdown_var, command=self._toggle_shutdown)
        self.chk_allow_shutdown.pack(side="left", padx=12)

        # Right side config
        cfg_frame = ttk.Frame(mid)
        cfg_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(cfg_frame, text="Poll interval (s):").pack(side="left")
        self.poll_var = tk.IntVar(value=self.cfg.poll_interval_sec)
        self.poll_entry = ttk.Entry(cfg_frame, width=6, textvariable=self.poll_var)
        self.poll_entry.pack(side="left", padx=6)

        ttk.Label(cfg_frame, text="Low %:").pack(side="left")
        self.low_var = tk.IntVar(value=self.cfg.low_battery_threshold_pct)
        self.low_entry = ttk.Entry(cfg_frame, width=6, textvariable=self.low_var)
        self.low_entry.pack(side="left", padx=6)

        ttk.Label(cfg_frame, text="Critical %:").pack(side="left")
        self.crit_var = tk.IntVar(value=self.cfg.critical_battery_threshold_pct)
        self.crit_entry = ttk.Entry(cfg_frame, width=6, textvariable=self.crit_var)
        self.crit_entry.pack(side="left", padx=6)

        # Bottom split: Logs and LLM Insight
        bottom = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        bottom.pack(fill="both", expand=True, padx=10, pady=10)

        log_frame = ttk.LabelFrame(bottom, text="Event log")
        llm_frame = ttk.LabelFrame(bottom, text="LLM insight")

        bottom.add(log_frame, weight=1)
        bottom.add(llm_frame, weight=1)

        # Log text
        self.log_text = tk.Text(log_frame, wrap="none", height=12)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

        # LLM panel
        llm_top = ttk.Frame(llm_frame)
        llm_top.pack(fill="x", padx=8, pady=8)

        self.llm_enable_var = tk.BooleanVar(value=self.cfg.llm_enabled)
        self.chk_llm = ttk.Checkbutton(llm_top, text="Enable LLM", variable=self.llm_enable_var, command=self._toggle_llm)
        self.chk_llm.pack(side="left", padx=6)

        ttk.Label(llm_top, text="Endpoint:").pack(side="left")
        self.llm_endpoint_var = tk.StringVar(value=self.cfg.llm_endpoint)
        self.llm_endpoint_entry = ttk.Entry(llm_top, width=28, textvariable=self.llm_endpoint_var)
        self.llm_endpoint_entry.pack(side="left", padx=6)

        ttk.Label(llm_top, text="Model:").pack(side="left")
        self.llm_model_var = tk.StringVar(value=self.cfg.llm_model)
        self.llm_model_entry = ttk.Entry(llm_top, width=16, textvariable=self.llm_model_var)
        self.llm_model_entry.pack(side="left", padx=6)

        ttk.Label(llm_top, text="API key:").pack(side="left")
        self.llm_key_var = tk.StringVar(value=self.cfg.llm_api_key)
        self.llm_key_entry = ttk.Entry(llm_top, width=20, textvariable=self.llm_key_var, show="*")
        self.llm_key_entry.pack(side="left", padx=6)

        self.btn_llm_now = ttk.Button(llm_top, text="Summarize now", command=self._llm_now)
        self.btn_llm_now.pack(side="left", padx=8)

        self.llm_text = tk.Text(llm_frame, wrap="word")
        self.llm_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.llm_text.insert("1.0", "LLM disabled.\n")

    def _labeled_value(self, parent: ttk.Frame, label: str, row: int) -> ttk.Label:
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        val = ttk.Label(parent, text="-")
        val.grid(row=row, column=1, sticky="w", padx=6, pady=2)
        return val

    def _bind_events(self):
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.monitor.stop()
        except Exception:
            pass
        self.destroy()

    def _toggle_shutdown(self):
        self.cfg.allow_shutdown_actions = bool(self.chk_allow_shutdown_var.get())
        self._log(f"Shutdown actions {'enabled' if self.cfg.allow_shutdown_actions else 'disabled'}.")

    def _toggle_llm(self):
        self.cfg.llm_enabled = bool(self.llm_enable_var.get())
        self.cfg.llm_endpoint = self.llm_endpoint_var.get().strip()
        self.cfg.llm_model = self.llm_model_var.get().strip()
        self.cfg.llm_api_key = self.llm_key_var.get().strip()
        self._log(f"LLM {'enabled' if self.cfg.llm_enabled else 'disabled'}.")

    def _refresh_now(self):
        st = self.monitor.poll_once()
        if st:
            self._apply_status(st)

    def _save_log(self):
        path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Log files", "*.log"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.log_lines))
            self._log(f"Log saved to {path}")
        except Exception as e:
            messagebox.showerror("Save log", f"Failed to save log: {e}")

    def _shutdown_test(self):
        # Safe test: no actual shutdown unless enabled; we record intent.
        if not self.cfg.allow_shutdown_actions:
            messagebox.showinfo("Shutdown", "Shutdown actions are disabled. Enable them to proceed.")
            return
        # Attempt a safe pre-shutdown action; in production you might trigger OS shutdown here.
        self._log("Shutdown test: would initiate system shutdown (guarded).")
        if psutil:
            try:
                # Example: close non-essential apps by name criteria? (Here we only log process count)
                procs = list(psutil.process_iter(attrs=["pid", "name"]))
                self._log(f"Running processes: {len(procs)} (no action taken).")
            except Exception as e:
                self._log(f"Process scan failed: {e}")

    def _drain_updates(self):
        # Update config from entries
        try:
            self.cfg.poll_interval_sec = int(self.poll_var.get())
            self.cfg.low_battery_threshold_pct = int(self.low_var.get())
            self.cfg.critical_battery_threshold_pct = int(self.crit_var.get())
        except Exception:
            pass

        drained = False
        while True:
            try:
                st = self.updates.get_nowait()
                self._apply_status(st)
                drained = True
            except queue.Empty:
                break

        # If nothing drained, re-check soon; otherwise, immediate next tick
        self.after(200 if drained else 500, self._drain_updates)

    def _apply_status(self, st: UPSStatus):
        self.last_status = st
        # Update labels
        self.lbl_source.config(text=st.source)
        self.lbl_on_battery.config(text=str(st.on_battery) if st.on_battery is not None else "-")
        self.lbl_percentage.config(text=f"{st.percentage:.1f}" if st.percentage is not None else "-")
        self.lbl_runtime.config(text=str(st.runtime_seconds) if st.runtime_seconds is not None else "-")
        self.lbl_vin.config(text=f"{st.voltage_in:.1f}" if st.voltage_in is not None else "-")
        self.lbl_vout.config(text=f"{st.voltage_out:.1f}" if st.voltage_out is not None else "-")
        self.lbl_load.config(text=f"{st.load_pct:.1f}" if st.load_pct is not None else "-")
        self.lbl_status.config(text=st.status_text or "-")

        # Progress + alerts
        pct = st.percentage if st.percentage is not None else 0.0
        self.progress["value"] = max(0, min(100, pct))

        alert_txt, alert_fg = self._compute_alert(pct, st.on_battery)
        self.alert_label.config(text=alert_txt, foreground=alert_fg)

        # Log line
        ts = datetime.fromtimestamp(st.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        self._log(f"[{ts}] {st.source} | batt={st.on_battery} | {pct:.1f}% | rt={st.runtime_seconds}s | load={st.load_pct}% | {st.status_text}")

    def _compute_alert(self, pct: float, on_battery: Optional[bool]) -> tuple[str, str]:
        if on_battery is True:
            if pct <= self.cfg.critical_battery_threshold_pct:
                return ("Critical: prepare to shut down", "#b00000")
            if pct <= self.cfg.low_battery_threshold_pct:
                return ("Low battery: reduce load and save work", "#b06a00")
            return ("On battery: monitor usage and runtime", "#004a8f")
        elif on_battery is False:
            if pct < 100:
                return ("Charging: stable power", "#007a3d")
            return ("Online: battery full", "#007a3d")
        else:
            return ("Unknown power state", "#444444")

    def _log(self, line: str):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"{ts} | {line}"
        self.log_lines.append(full)
        if len(self.log_lines) > self.cfg.log_capacity:
            self.log_lines = self.log_lines[-self.cfg.log_capacity:]

        self.log_text.configure(state="normal")
        self.log_text.insert("end", full + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _llm_now(self):
        self._toggle_llm()  # sync cfg with UI entries
        if not self.cfg.llm_enabled:
            messagebox.showinfo("LLM", "LLM is disabled.")
            return
        if not self.last_status:
            messagebox.showinfo("LLM", "No UPS status available yet.")
            return

        prompt = build_llm_prompt(self.last_status, self.cfg)

        def work():
            summary = call_llm(prompt, self.cfg)
            self.after(0, lambda: self._llm_set_text(summary or "No response."))

        threading.Thread(target=work, daemon=True).start()

    def _llm_set_text(self, text: str):
        self.llm_text.delete("1.0", "end")
        self.llm_text.insert("1.0", text or "")


# ------------------------------
# Entry point
# ------------------------------

def main():
    # Load optional config JSON
    cfg = AppConfig()
    cfg_path = os.path.join(os.path.dirname(__file__), "ups_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception:
            pass

    app = UPSApp(cfg)
    app.mainloop()


if __name__ == "__main__":
    main()
