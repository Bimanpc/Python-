#!/usr/bin/env python3
"""
SSH AI Assistant - Tkinter GUI SSH client with an LLM command helper.
Features:
  - SSH connection via paramiko (key or password auth)
  - Interactive terminal output pane + command input
  - AI side panel: explain last output, generate commands from plain English
"""

import os
import re
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    import paramiko
except ImportError:
    raise SystemExit("Missing dependency: pip install paramiko")

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class SSHSession:
    """Wrapper around a paramiko interactive shell."""

    def __init__(self):
        self.client = None
        self.channel = None

    def connect(self, host, port, username, password=None, key_path=None):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(
            hostname=host,
            port=port,
            username=username,
            timeout=10,
            allow_agent=True,
            look_for_keys=True,
        )
        if key_path:
            kwargs["key_filename"] = key_path
        elif password:
            kwargs["password"] = password
        self.client.connect(**kwargs)
        self.channel = self.client.invoke_shell(term="xterm", width=120, height=40)
        # Give the banner a moment to arrive
        self.channel.settimeout(0.5)
        try:
            banner = self.read_available()
        except Exception:
            banner = ""
        return banner

    def read_available(self) -> str:
        data = b""
        while self.channel.recv_ready():
            data += self.channel.recv(4096)
        return ANSI_RE.sub("", data.decode("utf-8", errors="replace"))

    def send(self, cmd: str):
        self.channel.send(cmd + "\n")

    def close(self):
        if self.client:
            self.client.close()


class LLMHelper:
    """Thin client for an OpenAI-compatible API (OpenAI, local Ollama, LM Studio...)."""

    def __init__(self, base_url=None, api_key=None, model="gpt-4o-mini"):
        if not HAS_OPENAI:
            raise RuntimeError("pip install openai")
        self.client = OpenAI(
            base_url=base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
        )
        self.model = model

    def ask(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=800,
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()


class SSHAIClient(tk.Tk):
    SYSTEM_PROMPT = (
        "You are a Linux command-line assistant embedded in an SSH client. "
        "Given the user's goal or recent terminal output, respond with: "
        "1) the exact command(s) to run in a fenced code block, "
        "2) a one-sentence risk note if the command is destructive. Be concise."
    )

    def __init__(self):
        super().__init__()
        self.title("SSH AI Assistant")
        self.geometry("1100x700")
        self.ssh = SSHSession()
        self.llm = None
        self.out_queue = queue.Queue()

        self._build_ui()
        self.after(100, self._poll_output)

    # ---------------- UI ----------------

    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")

        ttk.Label(top, text="Host:").grid(row=0, column=0)
        self.host_var = tk.StringVar(value="localhost")
        ttk.Entry(top, textvariable=self.host_var, width=18).grid(row=0, column=1, padx=2)

        ttk.Label(top, text="Port:").grid(row=0, column=2)
        self.port_var = tk.StringVar(value="22")
        ttk.Entry(top, textvariable=self.port_var, width=5).grid(row=0, column=3, padx=2)

        ttk.Label(top, text="User:").grid(row=0, column=4)
        self.user_var = tk.StringVar(value="root")
        ttk.Entry(top, textvariable=self.user_var, width=10).grid(row=0, column=5, padx=2)

        ttk.Label(top, text="Password:").grid(row=0, column=6)
        self.pass_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.pass_var, show="•", width=14).grid(row=0, column=7, padx=2)

        ttk.Label(top, text="Key:").grid(row=0, column=8)
        self.key_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.key_var, width=16).grid(row=0, column=9, padx=2)

        self.connect_btn = ttk.Button(top, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=10, padx=4)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=11)

        main = ttk.Frame(self, padding=(6, 0))
        main.pack(fill="both", expand=True)

        # --- Left: terminal ---
        left = ttk.LabelFrame(main, text="Terminal", padding=4)
        left.pack(side="left", fill="both", expand=True)

        self.terminal = scrolledtext.ScrolledText(left, bg="#11131a", fg="#e6e6e6",
                                                  insertbackground="#e6e6e6",
                                                  font=("Consolas", 10), state="disabled")
        self.terminal.pack(fill="both", expand=True)

        cmd_frame = ttk.Frame(left)
        cmd_frame.pack(fill="x", pady=3)
        ttk.Label(cmd_frame, text="$").pack(side="left")
        self.cmd_entry = ttk.Entry(cmd_frame, font=("Consolas", 10))
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.cmd_entry.bind("<Return>", lambda e: self.run_command())
        ttk.Button(cmd_frame, text="Run", command=self.run_command).pack(side="right")

        # --- Right: AI panel ---
        right = ttk.LabelFrame(main, text="AI Assistant", padding=4)
        right.pack(side="right", fill="both", padx=(6, 0))

        row = ttk.Frame(right); row.pack(fill="x")
        ttk.Label(row, text="Base URL:").pack(side="left")
        self.baseurl_var = tk.StringVar(value=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        ttk.Entry(row, textvariable=self.baseurl_var, width=22).pack(side="left", padx=2)

        row2 = ttk.Frame(right); row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="API key:").pack(side="left")
        self.apikey_var = tk.StringVar(value=os.getenv("OPENAI_API_KEY", ""))
        ttk.Entry(row2, textvariable=self.apikey_var, show="•", width=20).pack(side="left", padx=2)

        row3 = ttk.Frame(right); row3.pack(fill="x")
        ttk.Label(row3, text="Model:").pack(side="left")
        self.model_var = tk.StringVar(value="gpt-4o-mini")
        ttk.Entry(row3, textvariable=self.model_var, width=18).pack(side="left", padx=2)
        ttk.Button(row3, text="Init LLM", command=self.init_llm).pack(side="right")

        self.ai_goal = tk.Text(right, height=4, font=("Consolas", 9))
        self.ai_goal.pack(fill="x", pady=4)
        self.ai_goal.insert("1.0", "Describe what you want to do on the server...")

        btns = ttk.Frame(right); btns.pack(fill="x")
        ttk.Button(btns, text="Generate command", command=self.generate_cmd).pack(side="left", padx=2)
        ttk.Button(btns, text="Explain last output", command=self.explain_output).pack(side="left", padx=2)
        ttk.Button(btns, text="Send to terminal ▶", command=self.send_ai_cmd_to_terminal).pack(side="left", padx=2)

        self.ai_out = scrolledtext.ScrolledText(right, font=("Consolas", 9), width=45, state="disabled")
        self.ai_out.pack(fill="both", expand=True, pady=4)

    # ---------------- Helpers ----------------

    def term_append(self, text: str):
        self.terminal.configure(state="normal")
        self.terminal.insert("end", text)
        self.terminal.see("end")
        self.terminal.configure(state="disabled")

    def ai_append(self, text: str):
        self.ai_out.configure(state="normal")
        self.ai_out.insert("end", text + "\n")
        self.ai_out.see("end")
        self.ai_out.configure(state="disabled")

    @staticmethod
    def extract_code_block(text: str) -> str:
        m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        return m.group(1).strip() if m else ""

    def last_terminal_output(self) -> str:
        content = self.terminal.get("1.0", "end").strip()
        return content[-3000:] if len(content) > 3000 else content

    # ---------------- Actions ----------------

    def connect(self):
        try:
            key = self.key_var.get().strip() or None
            pwd = self.pass_var.get() or None
            banner = self.ssh.connect(
                self.host_var.get().strip(),
                int(self.port_var.get()),
                self.user_var.get().strip(),
                password=pwd,
                key_path=key,
            )
            self.term_append(banner)
            self.connect_btn.configure(state="disabled")
            threading.Thread(target=self._reader_loop, daemon=True).start()
        except Exception as e:
            messagebox.showerror("Connection failed", str(e))

    def disconnect(self):
        self.ssh.close()
        self.connect_btn.configure(state="normal")
        self.term_append("\n[disconnected]\n")

    def _reader_loop(self):
        while self.ssh.client and self.ssh.client.get_transport() \
                and self.ssh.client.get_transport().is_active():
            try:
                out = self.ssh.read_available()
                if out:
                    self.out_queue.put(out)
            except Exception:
                break
            self.after(200)  # avoid busy-wait using threading-friendly sleep-ish

    def _poll_output(self):
        try:
            while True:
                self.term_append(self.out_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_output)

    def run_command(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        if not self.ssh.channel:
            messagebox.showwarning("Not connected", "Connect to a host first.")
            return
        self.term_append(f"$ {cmd}\n")
        self.cmd_entry.delete(0, "end")
        self.ssh.send(cmd)

    def init_llm(self):
        try:
            self.llm = LLMHelper(self.baseurl_var.get().strip(), self.apikey_var.get().strip(),
                                 self.model_var.get().strip())
            self.ai_append("[LLM ready]")
        except Exception as e:
            messagebox.showerror("LLM init failed", str(e))

    def _llm_task(self, user_msg):
        self.ai_append("\n[thinking...]")
        try:
            reply = self.llm.ask(self.SYSTEM_PROMPT, user_msg)
            self.ai_append(reply)
            self.ai_append("-" * 40)
        except Exception as e:
            self.ai_append(f"[LLM error: {e}]")

    def generate_cmd(self):
        if not self.llm:
            self.init_llm()
            if not self.llm:
                return
        goal = self.ai_goal.get("1.0", "end").strip()
        threading.Thread(target=self._llm_task,
                         args=(f"Goal: {goal}",), daemon=True).start()

    def explain_output(self):
        if not self.llm:
            self.init_llm()
            if not self.llm:
                return
        threading.Thread(target=self._llm_task,
                         args=(f"Explain this terminal output:\n{self.last_terminal_output()}"),
                         daemon=True).start()

    def send_ai_cmd_to_terminal(self):
        cmd = self.extract_code_block(self.ai_out.get("1.0", "end"))
        if cmd:
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, cmd)
            self.run_command()
        else:
            messagebox.showinfo("No command", "No code block found in the AI response.")

    def on_close(self):
        self.ssh.close()
        self.destroy()


if __name__ == "__main__":
    app = SSHAIClient()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
