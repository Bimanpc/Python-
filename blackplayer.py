# remote_video_player_ai.py
# Requirements:
#   - Python 3.9+
#   - pip install python-vlc
#   - On Windows, install VLC (https://www.videolan.org/) so libvlc is available
#
# Optional LLM integration:
#   - Fill in execute_ai_command_llm() with your API call
#   - Example uses environment variable OPENAI_API_KEY (you can swap to your provider)
#
# Notes:
#   - Plays remote URLs via VLC (HTTP/HTTPS, many stream formats)
#   - Embeds VLC video inside Tkinter window (Windows set_hwnd)
#   - Local natural-language parsing for commands ("play", "pause", "seek 1:23", "volume 60", "open <url>")
#   - Queue multiple URLs; AI can "next" or "previous"
#
# Tested on Windows 11 with VLC 3.x and python-vlc.

import os
import re
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import simpledialog

try:
    import vlc
except ImportError:
    messagebox.showerror("Missing dependency", "python-vlc not installed. Run: pip install python-vlc")
    raise

APP_TITLE = "Remote Video Player + AI Commands"
DEFAULT_VOLUME = 70

class RemoteVideoPlayerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("980x620")

        # VLC state
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.playlist = []
        self.current_index = -1
        self.is_playing = False

        # UI layout
        self._build_ui()
        self._bind_events()

        # Periodic UI updates (time, slider)
        self._start_ui_loop()

    def _build_ui(self):
        # Top: URL entry and controls
        top = ttk.Frame(self.root, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var, width=60)
        self.url_entry.pack(side=tk.LEFT, padx=6)

        self.btn_add = ttk.Button(top, text="Add to queue", command=self.add_to_queue)
        self.btn_add.pack(side=tk.LEFT, padx=4)

        self.btn_open = ttk.Button(top, text="Open now", command=self.open_url_now)
        self.btn_open.pack(side=tk.LEFT, padx=4)

        # Middle: Video canvas
        video_frame = ttk.Frame(self.root, padding=4)
        video_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(video_frame, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._attach_player_to_canvas()

        # Playback controls
        controls = ttk.Frame(self.root, padding=8)
        controls.pack(side=tk.TOP, fill=tk.X)

        self.btn_play = ttk.Button(controls, text="Play", command=self.play)
        self.btn_pause = ttk.Button(controls, text="Pause", command=self.pause)
        self.btn_stop = ttk.Button(controls, text="Stop", command=self.stop)
        self.btn_prev = ttk.Button(controls, text="Previous", command=self.previous)
        self.btn_next = ttk.Button(controls, text="Next", command=self.next)

        self.btn_play.pack(side=tk.LEFT, padx=2)
        self.btn_pause.pack(side=tk.LEFT, padx=2)
        self.btn_stop.pack(side=tk.LEFT, padx=8)
        self.btn_prev.pack(side=tk.LEFT, padx=2)
        self.btn_next.pack(side=tk.LEFT, padx=2)

        ttk.Label(controls, text="Volume").pack(side=tk.LEFT, padx=(12, 4))
        self.volume_var = tk.IntVar(value=DEFAULT_VOLUME)
        self.volume_slider = ttk.Scale(controls, from_=0, to=100, orient=tk.HORIZONTAL, command=self.on_volume_change)
        self.volume_slider.set(DEFAULT_VOLUME)
        self.volume_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        # Seek bar + time labels
        seek_frame = ttk.Frame(self.root, padding=8)
        seek_frame.pack(side=tk.TOP, fill=tk.X)
        self.current_time_label = ttk.Label(seek_frame, text="00:00")
        self.total_time_label = ttk.Label(seek_frame, text="00:00")
        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_slider = ttk.Scale(seek_frame, from_=0, to=1000, orient=tk.HORIZONTAL, variable=self.seek_var, command=self.on_seek_drag)

        self.current_time_label.pack(side=tk.LEFT)
        self.seek_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.total_time_label.pack(side=tk.LEFT)

        # Bottom: Queue and AI command
        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        queue_frame = ttk.Frame(bottom)
        queue_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(queue_frame, text="Queue").pack(anchor="w")
        self.queue_list = tk.Listbox(queue_frame, height=6)
        self.queue_list.pack(fill=tk.BOTH, expand=True)
        self.queue_list.bind("<Double-Button-1>", self.on_queue_double_click)

        queue_btns = ttk.Frame(queue_frame)
        queue_btns.pack(fill=tk.X, pady=4)
        ttk.Button(queue_btns, text="Remove selected", command=self.remove_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(queue_btns, text="Clear queue", command=self.clear_queue).pack(side=tk.LEFT, padx=4)

        ai_frame = ttk.Frame(bottom)
        ai_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(ai_frame, text="AI command").pack(anchor="w")
        self.ai_var = tk.StringVar()
        self.ai_entry = ttk.Entry(ai_frame, textvariable=self.ai_var)
        self.ai_entry.pack(fill=tk.X, padx=4)

        ai_btns = ttk.Frame(ai_frame)
        ai_btns.pack(fill=tk.X, pady=4)
        ttk.Button(ai_btns, text="Parse locally", command=self.execute_ai_command_local).pack(side=tk.LEFT, padx=4)
        ttk.Button(ai_btns, text="Use LLM (stub)", command=self.execute_ai_command_llm).pack(side=tk.LEFT, padx=4)

        # Initialize player defaults
        self.player.audio_set_volume(DEFAULT_VOLUME)

    def _bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<space>", lambda e: self.toggle_play_pause())
        self.root.bind("<Control-Right>", lambda e: self.next())
        self.root.bind("<Control-Left>", lambda e: self.previous())

    def _attach_player_to_canvas(self):
        self.root.update_idletasks()
        handle = self.canvas.winfo_id()
        if sys.platform.startswith("win"):
            self.player.set_hwnd(handle)
        elif sys.platform.startswith("linux"):
            self.player.set_xwindow(handle)
        elif sys.platform.startswith("darwin"):
            # macOS embedding can be finicky; VLC may need additional setup.
            self.player.set_nsobject(handle)

    # ---------- Core playback ----------
    def add_to_queue(self):
        url = self.url_var.get().strip()
        if not url:
            return
        self.playlist.append(url)
        self.queue_list.insert(tk.END, url)

    def open_url_now(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a video URL.")
            return
        self._play_url(url)

    def on_queue_double_click(self, event):
        selection = self.queue_list.curselection()
        if not selection:
            return
        idx = selection[0]
        self.current_index = idx
        url = self.playlist[idx]
        self._play_url(url)

    def remove_selected(self):
        selection = self.queue_list.curselection()
        if not selection:
            return
        idx = selection[0]
        self.queue_list.delete(idx)
        del self.playlist[idx]
        if self.current_index == idx:
            self.stop()
            self.current_index = -1

    def clear_queue(self):
        self.queue_list.delete(0, tk.END)
        self.playlist.clear()
        self.stop()
        self.current_index = -1

    def _play_url(self, url):
        media = self.instance.media_new(url)
        self.player.set_media(media)

        # Autoplay with slight delay to ensure window handle is set
        def start_play():
            time.sleep(0.05)
            self.player.play()
            self.is_playing = True

        threading.Thread(target=start_play, daemon=True).start()

    def play(self):
        if self.player.get_media():
            self.player.play()
            self.is_playing = True
        elif self.playlist and self.current_index >= 0:
            self._play_url(self.playlist[self.current_index])
        elif self.playlist:
            self.current_index = 0
            self._play_url(self.playlist[0])

    def pause(self):
        if self.is_playing:
            self.player.pause()
            self.is_playing = False
        else:
            # Resume if paused
            self.player.pause()
            self.is_playing = True

    def toggle_play_pause(self):
        if self.player.can_pause():
            self.player.pause()
            self.is_playing = not self.is_playing

    def stop(self):
        self.player.stop()
        self.is_playing = False

    def previous(self):
        if not self.playlist:
            return
        self.current_index = max(0, self.current_index - 1)
        self._play_url(self.playlist[self.current_index])

    def next(self):
        if not self.playlist:
            return
        self.current_index = min(len(self.playlist) - 1, self.current_index + 1)
        self._play_url(self.playlist[self.current_index])

    # ---------- Volume & seek ----------
    def on_volume_change(self, value):
        try:
            vol = int(float(value))
            self.player.audio_set_volume(vol)
        except Exception:
            pass

    def on_seek_drag(self, value):
        # Seek proportionally when dragging slider
        try:
            pos = float(value) / 1000.0
            self.player.set_position(pos)
        except Exception:
            pass

    def _start_ui_loop(self):
        def update_loop():
            try:
                length_ms = self.player.get_length()
                if length_ms and length_ms > 0:
                    pos = self.player.get_position()
                    current_ms = int(length_ms * pos)
                    self.current_time_label.config(text=self._format_ms(current_ms))
                    self.total_time_label.config(text=self._format_ms(length_ms))
                    self.seek_slider.set(pos * 1000.0)
            except Exception:
                pass
            finally:
                self.root.after(200, update_loop)
        update_loop()

    @staticmethod
    def _format_ms(ms):
        if ms < 0:
            return "00:00"
        sec = int(ms / 1000)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    # ---------- AI command parsing ----------
    def execute_ai_command_local(self):
        cmd = self.ai_var.get().strip().lower()
        if not cmd:
            return
        handled = self._parse_and_execute(cmd)
        if not handled:
            messagebox.showinfo("AI parser", "Command not understood. Try: open <url>, play, pause, stop, next, previous, volume <0-100>, seek <mm:ss>")

    def _parse_and_execute(self, cmd: str) -> bool:
        # Open URL
        m = re.match(r"^(open|play)\s+(https?://\S+)$", cmd)
        if m:
            url = m.group(2)
            self.url_var.set(url)
            self._play_url(url)
            return True

        # Basic controls
        if cmd in ("play", "resume"):
            self.play(); return True
        if cmd in ("pause", "hold"):
            self.pause(); return True
        if cmd in ("stop", "end"):
            self.stop(); return True
        if cmd in ("next", "skip"):
            self.next(); return True
        if cmd in ("previous", "prev", "back"):
            self.previous(); return True

        # Volume
        m = re.match(r"^(volume|vol)\s*(\d{1,3})$", cmd)
        if m:
            vol = max(0, min(100, int(m.group(2))))
            self.volume_slider.set(vol)
            self.player.audio_set_volume(vol)
            return True

        m = re.match(r"^(volume|vol)\s*(up|down)$", cmd)
        if m:
            delta = 10 if m.group(2) == "up" else -10
            vol = max(0, min(100, self.player.audio_get_volume() + delta))
            self.volume_slider.set(vol)
            self.player.audio_set_volume(vol)
            return True

        # Seek "seek 1:23" or "seek to 1:23"
        m = re.match(r"^seek(?:\s+to)?\s+(\d{1,2}):(\d{2})$", cmd)
        if m:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            target_ms = (minutes * 60 + seconds) * 1000
            length_ms = self.player.get_length()
            if length_ms > 0:
                pos = max(0.0, min(1.0, target_ms / length_ms))
                self.player.set_position(pos)
                return True

        # Queue management
        m = re.match(r"^queue\s+(https?://\S+)$", cmd)
        if m:
            url = m.group(1)
            self.url_var.set(url)
            self.add_to_queue()
            return True

        # "play index 2"
        m = re.match(r"^play\s+index\s+(\d+)$", cmd)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(self.playlist):
                self.current_index = idx
                self._play_url(self.playlist[idx])
                return True

        return False

    def execute_ai_command_llm(self):
        """
        Optional: Replace this with your LLM integration.
        The function should take self.ai_var.get() and produce a normalized command
        that this app understands, then call _parse_and_execute().
        """
        user_text = self.ai_var.get().strip()
        if not user_text:
            return

        # Example prompt (you can improve/expand):
        # "User request: '<text>'. Return a single control command supported by the app:
        #   open <url> | play | pause | stop | next | previous | volume <0-100> | volume up | volume down | seek mm:ss | queue <url> | play index <n>"

        # For demo, we just pass through to local parser.
        if self._parse_and_execute(user_text):
            return

        # If you integrate an LLM, map its output to a single normalized command string, then:
        # normalized = llm_parse(user_text)
        # self._parse_and_execute(normalized)

        messagebox.showinfo("LLM stub", "Hook your LLM here to normalize complex requests into supported commands.")

    # ---------- Cleanup ----------
    def on_close(self):
        try:
            self.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    # Use system theme where available
    try:
        root.tk.call("source", "azure.tcl")
        root.tk.call("set_theme", "light")
    except Exception:
        pass
    app = RemoteVideoPlayerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
