import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

from PyQt5 import QtWidgets, QtGui, QtCore
import vlc  # Requires VLC installed

# Optional: OpenAI (replace with your own LLM provider if needed)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class VideoState:
    media: Optional[vlc.Media] = None
    filepath: Optional[str] = None
    duration_ms: int = 0
    playing: bool = False


class MP4PlayerAI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MP4 Player + AI")
        self.setMinimumSize(900, 600)

        # VLC player
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()

        # UI elements
        self.video_frame = QtWidgets.QFrame()
        self.video_frame.setFrameShape(QtWidgets.QFrame.Box)
        self.video_frame.setStyleSheet("background-color: #000;")

        self.open_btn = QtWidgets.QPushButton("Open")
        self.play_btn = QtWidgets.QPushButton("Play")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.stop_btn = QtWidgets.QPushButton("Stop")

        self.position_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setSingleStep(1)

        self.volume_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)

        self.time_label = QtWidgets.QLabel("00:00 / 00:00")
        self.file_label = QtWidgets.QLabel("No file loaded")

        # AI panel
        self.ai_prompt = QtWidgets.QTextEdit()
        self.ai_prompt.setPlaceholderText("Ask AI about the video, scene, or timestamp…")
        self.ai_btn = QtWidgets.QPushButton("Ask AI")
        self.ai_output = QtWidgets.QTextEdit()
        self.ai_output.setReadOnly(True)

        # Layouts
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(self.open_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.pause_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        controls.addWidget(QtWidgets.QLabel("Position"))
        controls.addWidget(self.position_slider)
        controls.addWidget(QtWidgets.QLabel("Volume"))
        controls.addWidget(self.volume_slider)

        info_bar = QtWidgets.QHBoxLayout()
        info_bar.addWidget(self.file_label)
        info_bar.addStretch(1)
        info_bar.addWidget(self.time_label)

        ai_box = QtWidgets.QVBoxLayout()
        ai_box.addWidget(QtWidgets.QLabel("AI prompt"))
        ai_box.addWidget(self.ai_prompt, stretch=3)
        ai_box.addWidget(self.ai_btn)
        ai_box.addWidget(QtWidgets.QLabel("AI output"))
        ai_box.addWidget(self.ai_output, stretch=4)

        main_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        video_container = QtWidgets.QWidget()
        video_layout = QtWidgets.QVBoxLayout(video_container)
        video_layout.addLayout(info_bar)
        video_layout.addWidget(self.video_frame, stretch=1)
        video_layout.addLayout(controls)
        main_split.addWidget(video_container)

        ai_container = QtWidgets.QWidget()
        ai_container.setMinimumWidth(320)
        ai_container.setMaximumWidth(420)
        ai_container.setLayout(ai_box)
        main_split.addWidget(ai_container)
        main_split.setStretchFactor(0, 4)
        main_split.setStretchFactor(1, 1)

        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(main_split)

        # State/timers
        self.state = VideoState()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.update_ui)

        # Events
        self.open_btn.clicked.connect(self.open_file)
        self.play_btn.clicked.connect(self.play)
        self.pause_btn.clicked.connect(self.pause)
        self.stop_btn.clicked.connect(self.stop)
        self.position_slider.sliderPressed.connect(self.pause_for_seek)
        self.position_slider.sliderReleased.connect(self.seek_to_slider)
        self.volume_slider.valueChanged.connect(self.change_volume)
        self.ai_btn.clicked.connect(self.ask_ai)

        # Bind VLC video output to our frame
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(self.video_frame.winId())
        elif sys.platform == "win32":
            self.player.set_hwnd(int(self.video_frame.winId()))
        else:  # macOS
            self.player.set_nsobject(int(self.video_frame.winId()))

        self.change_volume(self.volume_slider.value())

    # ---------- Player actions ----------

    def open_file(self):
        dlg = QtWidgets.QFileDialog(self, "Open MP4", "", "Video Files (*.mp4 *.mov *.m4v);;All Files (*.*)")
        if dlg.exec_():
            filepaths = dlg.selectedFiles()
            if not filepaths:
                return
            path = filepaths[0]
            self.load_media(path)

    def load_media(self, path: str):
        self.state.filepath = path
        self.file_label.setText(os.path.basename(path))

        media = self.instance.media_new(path)
        self.state.media = media
        self.player.set_media(media)

        # Parse media for duration (async + fallback)
        media.parse_with_options(vlc.MediaParseFlag.local, timeout=2_000)
        time.sleep(0.05)  # tiny wait for metadata
        duration = media.get_duration()
        self.state.duration_ms = max(duration, 0)

        self.play()

    def play(self):
        if self.state.media is None:
            return
        self.player.play()
        self.state.playing = True
        self.timer.start()

    def pause(self):
        if self.state.media is None:
            return
        self.player.pause()
        self.state.playing = False

    def stop(self):
        self.player.stop()
        self.state.playing = False
        self.position_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")

    def pause_for_seek(self):
        if self.state.playing:
            self.player.set_pause(1)

    def seek_to_slider(self):
        if self.state.duration_ms <= 0:
            return
        pos = self.position_slider.value() / 1000.0  # 0..1
        target_ms = int(pos * self.state.duration_ms)
        self.player.set_time(target_ms)
        if self.state.playing:
            self.player.set_pause(0)

    def change_volume(self, vol):
        self.player.audio_set_volume(int(vol))

    # ---------- UI updates ----------

    def update_ui(self):
        if self.state.media is None:
            return

        cur_ms = self.player.get_time()
        dur_ms = self.state.duration_ms or self.player.get_length()
        self.state.duration_ms = max(dur_ms, self.state.duration_ms)

        # slider pos
        if dur_ms > 0:
            pos = int((cur_ms / dur_ms) * 1000)
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(max(0, min(1000, pos)))
            self.position_slider.blockSignals(False)

        # time label
        self.time_label.setText(f"{self._fmt_ms(cur_ms)} / {self._fmt_ms(dur_ms)}")

        # stop timer when ended
        if dur_ms > 0 and cur_ms >= dur_ms and self.state.playing:
            self.stop()
            self.timer.stop()

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        if ms <= 0:
            return "00:00"
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    # ---------- AI integration ----------

    def ask_ai(self):
        prompt = self.ai_prompt.toPlainText().strip()
        if not prompt:
            self.ai_output.setPlainText("Enter a prompt for the AI.")
            return

        # Context: file + timestamp
        filename = self.state.filepath or "Unknown file"
        timestamp = self._fmt_ms(self.player.get_time())

        self.ai_output.setPlainText("Thinking…")

        def run_llm():
            try:
                return self.llm_respond(prompt, filename, timestamp)
            except Exception as e:
                return f"Error: {e}"

        # run in thread to avoid blocking UI
        worker = Worker(run_llm)
        worker.finished_with_result.connect(self.ai_output.setPlainText)
        worker.start()

    def llm_respond(self, user_prompt: str, filename: str, timestamp: str) -> str:
        """
        Sends a structured prompt to an LLM. Default: OpenAI GPT-4o mini (adjust model).
        Replace with your provider/client as needed.
        """
        sys_prompt = (
            "You are an assistant helping with video insights. "
            "You only respond with concise, actionable insights. "
            "If lacking visual/audio details, ask a targeted follow-up."
        )
        context = (
            f"Video file: {filename}\n"
            f"Current timestamp: {timestamp}\n\n"
            f"User prompt: {user_prompt}\n"
        )

        if OPENAI_AVAILABLE and os.getenv("OPENAI_API_KEY"):
            openai.api_key = os.getenv("OPENAI_API_KEY")
            # Use Chat Completions for broad compatibility
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": context},
                ],
                temperature=0.3,
            )
            return resp.choices[0].message["content"].strip()

        # Fallback: echo + guidance
        return (
            "LLM not configured.\n\n"
            "Context received:\n" + context +
            "\nSet OPENAI_API_KEY and install `openai`, or swap in your own LLM client."
        )


class Worker(QtCore.QThread):
    finished_with_result = QtCore.pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        result = self.fn()
        self.finished_with_result.emit(result)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MP4PlayerAI()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
