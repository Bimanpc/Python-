# -*- coding: utf-8 -*-
# Windows XP AI LLM Media Player Classic-style (Python 2.7)
# Dependencies: comtypes, requests, simplejson
#
# pip install comtypes requests simplejson
#
# Set your LLM endpoint in the constants below. This is a minimal HTTP JSON contract.

import os
import sys
import time
import threading

# Tkinter in Python 2.7
import Tkinter as tk
import tkFileDialog
import tkMessageBox

# HTTP for LLM
import requests
try:
    import simplejson as json
except:
    import json

# comtypes for DirectShow
import comtypes
import comtypes.client
from comtypes import GUID, HRESULT
from ctypes import POINTER, byref, c_long, c_int, c_double, windll

# DirectShow GUIDs and interfaces
# Minimal subset for FilterGraph, MediaControl, MediaSeeking, BasicAudio, and VideoWindow

CLSID_FilterGraph = GUID('{E436EBB3-524F-11CE-9F53-0020AF0BA770}')
IID_IGraphBuilder = GUID('{56A868A9-0AD4-11CE-B03A-0020AF0BA770}')
IID_IMediaControl = GUID('{56A868B1-0AD4-11CE-B03A-0020AF0BA770}')
IID_IMediaSeeking = GUID('{36B73880-C2C8-11CF-8B46-00805F6CEF60}')
IID_IBasicAudio   = GUID('{56A868B3-0AD4-11CE-B03A-0020AF0BA770}')
IID_IVideoWindow  = GUID('{56A868B4-0AD4-11CE-B03A-0020AF0BA770}')

# LLM settings — replace with your endpoint
LLM_API_URL = 'http://127.0.0.1:8000/v1/chat'  # Example local endpoint
LLM_API_KEY = ''  # Optional; add header if needed
LLM_MODEL   = 'my-llm'  # Model name for your backend

# Utility: format time
def fmt_time(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    m = int(seconds) // 60
    s = int(seconds) % 60
    return "%02d:%02d" % (m, s)

class DirectShowPlayer(object):
    def __init__(self, video_hwnd):
        # Create FilterGraph
        comtypes.CoInitialize()
        self.graph = comtypes.client.CreateObject(CLSID_FilterGraph, interface=comtypes.gen.DirectShowLib.IGraphBuilder)
        # Lazy import of generated interfaces if first time
        self.gb = self.graph

        # Query interfaces
        self.mc = self.gb.QueryInterface(comtypes.gen.DirectShowLib.IMediaControl)
        self.ms = self.gb.QueryInterface(comtypes.gen.DirectShowLib.IMediaSeeking)
        self.ba = self.gb.QueryInterface(comtypes.gen.DirectShowLib.IBasicAudio)
        self.vw = None
        try:
            self.vw = self.gb.QueryInterface(comtypes.gen.DirectShowLib.IVideoWindow)
        except:
            self.vw = None

        self.duration = None
        self.video_hwnd = video_hwnd
        self.current_file = None
        self._setup_video_window()

    def _setup_video_window(self):
        if self.vw:
            self.vw.put_Owner(self.video_hwnd)
            self.vw.put_WindowStyle(0x40000000 | 0x10000000)  # WS_CHILD | WS_CLIPSIBLINGS
            # Resize handled externally via set_bounds

    def set_bounds(self, x, y, w, h):
        if self.vw:
            try:
                self.vw.SetWindowPosition(x, y, w, h)
            except:
                pass

    def open(self, path):
        self.stop()
        # Render file
        hr = self.gb.RenderFile(path, None)
        self.current_file = path
        # Setup video owner again (filters may have changed)
        self._setup_video_window()
        # Query duration
        try:
            # Use REFERENCE_TIME (100-ns units)
            format_guid = comtypes.gen.DirectShowLib.TIME_FORMAT_MEDIA_TIME
            self.ms.SetTimeFormat(format_guid)
            dur = self.ms.GetDuration()
            # Convert to seconds: 100 ns = 1e-7 s
            self.duration = dur / 10000000.0
        except:
            self.duration = None

    def play(self):
        try:
            self.mc.Run()
        except:
            pass

    def pause(self):
        try:
            self.mc.Pause()
        except:
            pass

    def stop(self):
        try:
            self.mc.Stop()
        except:
            pass

    def is_playing(self):
        # We can poll position change; for simplicity, assume playing if not stopped
        return True

    def get_position(self):
        try:
            pos = self.ms.GetCurrentPosition()
            return pos / 10000000.0
        except:
            return 0.0

    def set_position(self, seconds):
        try:
            rt = int(seconds * 10000000.0)
            self.ms.SetPositions(rt, comtypes.gen.DirectShowLib.AM_SEEKING_AbsolutePositioning, None, comtypes.gen.DirectShowLib.AM_SEEKING_NoPositioning)
        except:
            pass

    def set_volume(self, vol_0_100):
        # IBasicAudio volume is in hundredths of dB, range typically -10000 to 0
        try:
            v = int(-10000 + (vol_0_100 * 100))  # crude map: 0 -> -10000, 100 -> 0
            if v > 0: v = 0
            if v < -10000: v = -10000
            self.ba.put_Volume(v)
        except:
            pass

    def cleanup(self):
        try:
            self.stop()
        except:
            pass
        try:
            comtypes.CoUninitialize()
        except:
            pass


class MPCApp(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("AI LLM Media Player (XP MPC-style)")
        self.geometry("900x600")

        # Main panes: left video, right playlist + AI
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # Video panel (frame with HWND)
        self.video_frame = tk.Frame(self, bg="#000000")
        self.video_frame.grid(row=0, column=0, sticky="nsew")
        self.update_idletasks()
        self.video_hwnd = self._get_hwnd(self.video_frame)

        # Player
        self.player = DirectShowPlayer(self.video_hwnd)

        # Right panel: playlist + AI
        right = tk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Playlist
        pl_frame = tk.LabelFrame(right, text="Playlist")
        pl_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        pl_frame.rowconfigure(0, weight=1)
        pl_frame.columnconfigure(0, weight=1)

        self.playlist = tk.Listbox(pl_frame, height=12)
        self.playlist.grid(row=0, column=0, sticky="nsew")
        self.playlist.bind("<Double-Button-1>", self.on_playlist_play)

        pl_btns = tk.Frame(pl_frame)
        pl_btns.grid(row=1, column=0, sticky="ew")
        tk.Button(pl_btns, text="Add...", command=self.on_add_files, width=10).pack(side="left", padx=3, pady=3)
        tk.Button(pl_btns, text="Remove", command=self.on_remove_selected, width=10).pack(side="left", padx=3, pady=3)
        tk.Button(pl_btns, text="Clear", command=self.on_clear_playlist, width=10).pack(side="left", padx=3, pady=3)

        # AI panel
        ai_frame = tk.LabelFrame(right, text="AI LLM")
        ai_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        ai_frame.rowconfigure(0, weight=1)
        ai_frame.columnconfigure(0, weight=1)

        self.ai_input = tk.Text(ai_frame, height=6)
        self.ai_input.grid(row=0, column=0, sticky="nsew")

        ai_controls = tk.Frame(ai_frame)
        ai_controls.grid(row=1, column=0, sticky="ew")
        tk.Button(ai_controls, text="Send", command=self.on_ai_send, width=8).pack(side="left", padx=3, pady=3)
        self.ai_status = tk.Label(ai_controls, text="", anchor="w")
        self.ai_status.pack(side="left", padx=6)

        self.ai_output = tk.Text(ai_frame, height=10, state="disabled")
        self.ai_output.grid(row=2, column=0, sticky="nsew")

        # Bottom controls: Open, Play/Pause, Stop, Seek, Time, Volume
        controls = tk.Frame(self)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        tk.Button(controls, text="Open", command=self.on_open, width=8).pack(side="left", padx=3)
        self.play_pause_btn = tk.Button(controls, text="Play", command=self.on_play_pause, width=8)
        self.play_pause_btn.pack(side="left", padx=3)
        tk.Button(controls, text="Stop", command=self.on_stop, width=8).pack(side="left", padx=3)

        self.seek_var = tk.DoubleVar()
        self.seek = tk.Scale(controls, from_=0, to=1000, orient="horizontal", length=400,
                             variable=self.seek_var, command=self.on_seek_drag)
        self.seek.pack(side="left", padx=6)

        self.time_label = tk.Label(controls, text="00:00 / 00:00")
        self.time_label.pack(side="left", padx=6)

        tk.Label(controls, text="Vol").pack(side="left", padx=6)
        self.vol_var = tk.IntVar()
        self.volume = tk.Scale(controls, from_=0, to=100, orient="horizontal", length=120,
                               variable=self.vol_var, command=self.on_volume)
        self.volume.set(80)
        self.volume.pack(side="left")

        # Window resize bind to adjust video bounds
        self.video_frame.bind("<Configure>", self.on_video_resize)

        # Polling for UI updates (seek/time)
        self._poll_ui()

        # Close handler
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _get_hwnd(self, widget):
        # Get HWND for Tk window/frame
        # Uses Tk's internal handle via win32 API
        try:
            widget.update_idletasks()
            hwnd = widget.winfo_id()
            return hwnd
        except Exception as e:
            tkMessageBox.showerror("Error", "Failed to obtain window handle: %s" % e)
            return None

    def on_video_resize(self, event):
        # Fit video to frame
        try:
            self.player.set_bounds(0, 0, event.width, event.height)
        except:
            pass

    def on_open(self):
        path = tkFileDialog.askopenfilename(title="Open media",
                                            filetypes=[("Media files", "*.*"),
                                                       ("Video", "*.mp4;*.avi;*.wmv;*.mpg;*.mpeg;*.mkv"),
                                                       ("Audio", "*.mp3;*.wav;*.wma;*.aac")])
        if path:
            self._open_file(path)

    def _open_file(self, path):
        try:
            self.player.open(path)
            self.player.play()
            self.play_pause_btn.config(text="Pause")
            self._add_to_playlist(path)
        except Exception as e:
            tkMessageBox.showerror("Open failed", str(e))

    def on_play_pause(self):
        # Toggle between play/pause
        btn = self.play_pause_btn.cget("text")
        try:
            if btn == "Play":
                self.player.play()
                self.play_pause_btn.config(text="Pause")
            else:
                self.player.pause()
                self.play_pause_btn.config(text="Play")
        except:
            pass

    def on_stop(self):
        self.player.stop()
        self.play_pause_btn.config(text="Play")

    def on_seek_drag(self, _val):
        # Map slider to duration
        dur = self.player.duration
        if dur and dur > 0:
            pos = (self.seek_var.get() / 1000.0) * dur
            self.player.set_position(pos)

    def on_volume(self, _val):
        try:
            self.player.set_volume(self.vol_var.get())
        except:
            pass

    def _poll_ui(self):
        # Update time and seek slider periodically
        try:
            dur = self.player.duration
            pos = self.player.get_position()
            if dur and dur > 0:
                self.seek_var.set(int((pos / dur) * 1000.0))
                self.time_label.config(text="%s / %s" % (fmt_time(pos), fmt_time(dur)))
            else:
                self.time_label.config(text="%s / %s" % (fmt_time(pos), fmt_time(None)))
        except:
            pass
        # Re-run after 200 ms
        self.after(200, self._poll_ui)

    def _add_to_playlist(self, path):
        # Avoid duplicates
        items = list(self.playlist.get(0, tk.END))
        if path not in items:
            self.playlist.insert(tk.END, path)

    def on_add_files(self):
        paths = tkFileDialog.askopenfilenames(title="Add to playlist",
                                              filetypes=[("Media files", "*.*")])
        if isinstance(paths, tuple) or isinstance(paths, list):
            for p in paths:
                self._add_to_playlist(p)

    def on_remove_selected(self):
        sel = list(self.playlist.curselection())
        sel.reverse()
        for i in sel:
            self.playlist.delete(i)

    def on_clear_playlist(self):
        self.playlist.delete(0, tk.END)

    def on_playlist_play(self, _evt):
        sel = self.playlist.curselection()
        if sel:
            path = self.playlist.get(sel[0])
            self._open_file(path)

    # --- AI LLM ---

    def on_ai_send(self):
        prompt = self.ai_input.get("1.0", "end").strip()
        if not prompt:
            self._ai_set_status("Enter a prompt.")
            return
        self._ai_set_status("Sending...")
        t = threading.Thread(target=self._ai_call, args=(prompt,))
        t.daemon = True
        t.start()

    def _ai_set_status(self, msg):
        self.ai_status.config(text=msg)

    def _ai_append_output(self, text):
        self.ai_output.config(state="normal")
        self.ai_output.insert("end", text + "\n")
        self.ai_output.see("end")
        self.ai_output.config(state="disabled")

    def _ai_call(self, prompt):
        try:
            headers = {'Content-Type': 'application/json'}
            if LLM_API_KEY:
                headers['Authorization'] = 'Bearer ' + LLM_API_KEY
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ]
            }
            resp = requests.post(LLM_API_URL, data=json.dumps(payload), headers=headers, timeout=30)
            if resp.status_code != 200:
                self._ai_set_status("Error %d" % resp.status_code)
                return
            data = resp.json()
            # Try common response shapes
            text = None
            if isinstance(data, dict):
                # OpenAI-like
                try:
                    text = data['choices'][0]['message']['content']
                except:
                    pass
                # Generic 'answer' field
                if text is None:
                    text = data.get('answer', '')
            if not text:
                text = json.dumps(data, indent=2)
            self._ai_append_output(text)
            self._ai_set_status("OK")
        except Exception as e:
            self._ai_set_status("Failed")
            self._ai_append_output("Error: %s" % str(e))

    def on_close(self):
        try:
            self.player.cleanup()
        except:
            pass
        self.destroy()


def main():
    app = MPCApp()
    app.mainloop()

if __name__ == "__main__":
    main()
