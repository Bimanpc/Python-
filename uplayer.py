# tk_llm_video_player.py
# Requirements: pip install python-vlc
# Optional: add your LLM in LLMClient.call_llm()

import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import vlc
except ImportError:
    raise RuntimeError("python-vlc is required. Install with: pip install python-vlc")


class VideoPlayer:
    def __init__(self, root):
        self.root = root
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.media = None

        self.is_fullscreen = False
        self._build_ui()
        self._bind_events()

        # Timer to update time labels/slider
        self._update_ui_timer()

    def _build_ui(self):
        self.root.title("LLM Video Player (Tk + VLC)")
        self.root.geometry("980x640")

        # Main layout: left video, right controls/prompt
        self.main = ttk.Frame(self.root)
        self.main.pack(fill="both", expand=True)

        self.left = ttk.Frame(self.main)
        self.left.pack(side="left", fill="both", expand=True)

        self.right = ttk.Frame(self.main, width=300)
        self.right.pack(side="right", fill="y")
        self.right.pack_propagate(False)

        # Video panel
        self.video_panel = tk.Canvas(self.left, background="#000000", highlightthickness=0)
        self.video_panel.pack(fill="both", expand=True)

        # Playback controls
        controls = ttk.Frame(self.left)
        controls.pack(fill="x")

        self.btn_open = ttk.Button(controls, text="Open", command=self.open_file_dialog)
        self.btn_play = ttk.Button(controls, text="Play", command=self.play)
        self.btn_pause = ttk.Button(controls, text="Pause", command=self.pause)
        self.btn_stop = ttk.Button(controls, text="Stop", command=self.stop)

        self.btn_open.pack(side="left", padx=4, pady=4)
        self.btn_play.pack(side="left", padx=4, pady=4)
        self.btn_pause.pack(side="left", padx=4, pady=4)
        self.btn_stop.pack(side="left", padx=4, pady=4)

        # Time/seek
        self.time_frame = ttk.Frame(self.left)
        self.time_frame.pack(fill="x")
        self.lbl_time = ttk.Label(self.time_frame, text="00:00 / 00:00")
        self.lbl_time.pack(side="left", padx=6)

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_slider = ttk.Scale(self.time_frame, orient="horizontal", variable=self.seek_var,
                                     from_=0.0, to=1000.0, command=self._on_seek_slider)
        self.seek_slider.pack(side="left", fill="x", expand=True, padx=6)

        # Volume/speed
        vs_frame = ttk.Frame(self.left)
        vs_frame.pack(fill="x")
        ttk.Label(vs_frame, text="Vol").pack(side="left", padx=(6, 0))
        self.vol_var = tk.IntVar(value=80)
        self.vol_slider = ttk.Scale(vs_frame, orient="horizontal", from_=0, to=100,
                                    command=self._on_volume_change)
        self.vol_slider.set(self.vol_var.get())
        self.vol_slider.pack(side="left", padx=6)

        ttk.Label(vs_frame, text="Speed").pack(side="left", padx=(12, 0))
        self.speed_var = tk.DoubleVar(value=1.0)
        self.speed_slider = ttk.Scale(vs_frame, orient="horizontal", from_=0.25, to=2.0,
                                      command=self._on_speed_change)
        self.speed_slider.set(self.speed_var.get())
        self.speed_slider.pack(side="left", padx=6)

        self.btn_mute = ttk.Button(vs_frame, text="Mute", command=self.toggle_mute)
        self.btn_fs = ttk.Button(vs_frame, text="Fullscreen", command=self.toggle_fullscreen)
        self.btn_mute.pack(side="right", padx=6)
        self.btn_fs.pack(side="right", padx=6)

        # Command + output (LLM/Parser)
        ttk.Label(self.right, text="Command").pack(anchor="w", padx=8, pady=(8, 2))
        self.cmd_entry = tk.Text(self.right, height=5, wrap="word")
        self.cmd_entry.pack(fill="x", padx=8)
        self.btn_run_cmd = ttk.Button(self.right, text="Run", command=self.run_command_async)
        self.btn_run_cmd.pack(padx=8, pady=(6, 10), anchor="e")

        ttk.Label(self.right, text="Console").pack(anchor="w", padx=8)
        self.console = tk.Text(self.right, height=20, state="disabled", wrap="word")
        self.console.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        # Attach VLC to Tk canvas
        self.root.after(100, self._attach_player)

    def _bind_events(self):
        self.root.bind("<Configure>", lambda e: self._resize_video())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _attach_player(self):
        handle = self.video_panel.winfo_id()
        if sys.platform.startswith("win"):
            self.player.set_hwnd(handle)
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(handle)
        elif sys.platform == "darwin":
            self.player.set_nsobject(handle)
        # Set initial volume
        self.player.audio_set_volume(self.vol_var.get())

    def _resize_video(self):
        # VLC handles scaling; no-op but kept for future custom behaviors
        pass

    def open_file_dialog(self):
        path = filedialog.askopenfilename(
            title="Open video",
            filetypes=[("Video files", "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.ts;*.flv;*.wmv;*.m4v"), ("All files", "*.*")]
        )
        if path:
            self.open_media(path)

    def open_media(self, path_or_url: str):
        try:
            self.media = self.instance.media_new(path_or_url)
            self.player.set_media(self.media)
            self.play()
            self._log(f"Opened: {path_or_url}")
        except Exception as e:
            messagebox.showerror("Open media failed", str(e))
            self._log(f"Error: {e}")

    def play(self):
        try:
            self.player.play()
            # Apply current speed
            rate = self.speed_var.get()
            try:
                self.player.set_rate(rate)
            except Exception:
                pass
        except Exception as e:
            self._log(f"Play error: {e}")

    def pause(self):
        try:
            self.player.pause()
        except Exception as e:
            self._log(f"Pause error: {e}")

    def stop(self):
        try:
            self.player.stop()
        except Exception as e:
            self._log(f"Stop error: {e}")

    def toggle_mute(self):
        try:
            self.player.audio_toggle_mute()
        except Exception as e:
            self._log(f"Mute error: {e}")

    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)

    def _on_volume_change(self, _value):
        v = int(float(self.vol_slider.get()))
        self.vol_var.set(v)
        try:
            self.player.audio_set_volume(v)
        except Exception as e:
            self._log(f"Volume error: {e}")

    def _on_speed_change(self, _value):
        rate = float(self.speed_slider.get())
        self.speed_var.set(rate)
        try:
            self.player.set_rate(rate)
        except Exception as e:
            self._log(f"Speed error: {e}")

    def _on_seek_slider(self, _value):
        # Slider is 0..1000; map to duration
        length_ms = self.player.get_length()
        if length_ms > 0:
            pos = self.seek_var.get() / 1000.0
            new_time = int(length_ms * pos)
            try:
                self.player.set_time(new_time)
            except Exception as e:
                self._log(f"Seek error: {e}")

    def _format_time(self, ms):
        if ms < 0:
            return "00:00"
        s = int(ms // 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _update_ui_timer(self):
        try:
            length = self.player.get_length()
            current = self.player.get_time()
            if length > 0:
                pos = max(0.0, min(1.0, current / length))
                self.seek_var.set(pos * 1000.0)
            self.lbl_time.config(text=f"{self._format_time(current)} / {self._format_time(length)}")
        except Exception:
            pass
        self.root.after(200, self._update_ui_timer)

    def _log(self, text):
        self.console.config(state="normal")
        self.console.insert("end", text + "\n")
        self.console.see("end")
        self.console.config(state="disabled")

    def on_close(self):
        try:
            self.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self.root.destroy()


# --- Command parsing and optional LLM integration ---

class LLMClient:
    """
    Plug your LLM provider inside call_llm() and return a normalized intent dict.
    For example:
      - {"action": "open", "target": "C:\\video.mp4"}
      - {"action": "seek", "seconds": 10, "direction": "forward"}
      - {"action": "volume", "value": 70}
      - {"action": "speed", "value": 1.25}
      - {"action": "play"} | {"action": "pause"} | {"action": "stop"}
      - {"action": "mute"} | {"action": "unmute"} | {"action": "fullscreen"} | {"action": "windowed"}
    """
    def __init__(self):
        self.enabled = bool(os.environ.get("LLM_ENABLED", "").strip())

    def parse(self, text: str) -> dict:
        """
        If LLM enabled, use it; otherwise use the local parser.
        """
        if self.enabled:
            return self.call_llm(text)
        return LocalParser.parse(text)

    def call_llm(self, text: str) -> dict:
        """
        Implement your LLM call and map the response to an intent dict.
        This stub falls back to local parser to keep the app functional.
        """
        # Example (pseudo):
        #   key = os.environ["API_KEY"]
        #   endpoint = os.environ.get("LLM_ENDPOINT")
        #   resp = requests.post(endpoint, headers=..., json={"prompt": text})
        #   intent = your_mapping(resp.json())
        # Return intent dict.
        return LocalParser.parse(text)


class LocalParser:
    """
    Fast, deterministic parser that supports concise commands and natural phrases.
    """
    OPEN_PATTERNS = [
        r"open\s+(?P<target>.+)$",
        r"play\s+(?P<target>https?://\S+)",
    ]

    @staticmethod
    def parse(text: str) -> dict:
        t = text.strip().lower()

        # Open file/url
        for pat in LocalParser.OPEN_PATTERNS:
            m = re.search(pat, t, flags=re.IGNORECASE)
            if m:
                target = m.group("target").strip().strip('"').strip("'")
                return {"action": "open", "target": target}

        # Play / Pause / Stop
        if re.search(r"\bplay\b", t):
            return {"action": "play"}
        if re.search(r"\bpause\b", t):
            return {"action": "pause"}
        if re.search(r"\bstop\b", t):
            return {"action": "stop"}

        # Seek forward/backward N seconds or to mm:ss
        m = re.search(r"(seek|skip|jump)\s+(forward|ahead|back|backward)?\s*(?P<sec>\d+)\s*(sec|second|seconds)?", t)
        if m:
            sec = int(m.group("sec"))
            direction = m.group(2) or "forward"
            return {"action": "seek", "seconds": sec, "direction": direction}

        m = re.search(r"(seek|go to|jump to)\s+(?P<mm>\d{1,2}):(?P<ss>\d{2})", t)
        if m:
            mm = int(m.group("mm"))
            ss = int(m.group("ss"))
            return {"action": "seek_to", "ms": (mm * 60 + ss) * 1000}

        # Volume
        m = re.search(r"(vol|volume)\s*(to|=)?\s*(?P<val>\d{1,3})", t)
        if m:
            val = max(0, min(100, int(m.group("val"))))
            return {"action": "volume", "value": val}
        if re.search(r"\bmute\b", t):
            return {"action": "mute"}
        if re.search(r"\bunmute\b", t):
            return {"action": "unmute"}

        # Speed
        m = re.search(r"(speed|rate)\s*(to|=)?\s*(?P<val>\d+(\.\d+)?)", t)
        if m:
            val = float(m.group("val"))
            return {"action": "speed", "value": max(0.25, min(3.0, val))}

        # Fullscreen/windowed
        if re.search(r"\bfullscreen\b", t):
            return {"action": "fullscreen"}
        if re.search(r"\bwindow(ed)?\b", t):
            return {"action": "windowed"}

        return {"action": "unknown", "raw": text}

# --- Command executor ---

class CommandExecutor:
    def __init__(self, player: VideoPlayer):
        self.player = player

    def execute(self, intent: dict):
        action = intent.get("action")
        if action == "open":
            target = intent.get("target")
            if target:
                self.player.open_media(target)
            else:
                self.player._log("No target found for open.")
        elif action == "play":
            self.player.play()
        elif action == "pause":
            self.player.pause()
        elif action == "stop":
            self.player.stop()
        elif action == "seek":
            seconds = intent.get("seconds", 0)
            direction = intent.get("direction", "forward")
            cur = self.player.player.get_time()
            delta = seconds * 1000 * (1 if direction.startswith("for") or direction.startswith("ahead") else -1)
            self.player.player.set_time(max(0, cur + delta))
        elif action == "seek_to":
            ms = intent.get("ms", 0)
            self.player.player.set_time(ms)
        elif action == "volume":
            val = intent.get("value", 80)
            self.player.vol_slider.set(val)
            self.player._on_volume_change(val)
        elif action == "mute":
            self.player.player.audio_set_mute(True)
        elif action == "unmute":
            self.player.player.audio_set_mute(False)
        elif action == "speed":
            val = intent.get("value", 1.0)
            self.player.speed_slider.set(val)
            self.player._on_speed_change(val)
        elif action == "fullscreen":
            if not self.player.is_fullscreen:
                self.player.toggle_fullscreen()
        elif action == "windowed":
            if self.player.is_fullscreen:
                self.player.toggle_fullscreen()
        else:
            self.player._log(f"Unknown command: {intent.get('raw', '')}")


# --- App wiring ---

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.player = VideoPlayer(self.root)
        self.llm = LLMClient()
        self.exec = CommandExecutor(self.player)

    def run_command_async(self):
        text = self.player.cmd_entry.get("1.0", "end").strip()
        if not text:
            return
        self.player._log(f"> {text}")
        threading.Thread(target=self._process_command, args=(text,), daemon=True).start()

    def _process_command(self, text: str):
        try:
            intent = self.llm.parse(text)
            self.exec.execute(intent)
        except Exception as e:
            self.player._log(f"Command error: {e}")

    def start(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().start()
