import tkinter as tk
from tkinter import ttk
import subprocess
import re
import threading

class WifiAnalyzer:
    def __init__(self, root):
        self.root = root
        self.root.title("WiFi Analyzer")
        self.root.geometry("900x500")
        self.root.resizable(True, True)

        title = tk.Label(
            root,
            text="WiFi Analyzer",
            font=("Arial", 18, "bold")
        )
        title.pack(pady=10)

        btn_frame = tk.Frame(root)
        btn_frame.pack(fill="x")

        self.scan_btn = tk.Button(
            btn_frame,
            text="Scan WiFi",
            command=self.start_scan,
            bg="#4CAF50",
            fg="white",
            width=15
        )
        self.scan_btn.pack(side="left", padx=5)

        self.auto_var = tk.BooleanVar()

        self.auto_check = tk.Checkbutton(
            btn_frame,
            text="Auto Refresh",
            variable=self.auto_var,
            command=self.auto_refresh
        )
        self.auto_check.pack(side="left", padx=10)

        columns = (
            "SSID",
            "Signal",
            "Channel",
            "Security"
        )

        self.tree = ttk.Treeview(
            root,
            columns=columns,
