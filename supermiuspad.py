#!/usr/bin/env python3
# Vista-like WordPad with AI LLM panel (Tkinter, single-file)
# Tested on Python 3.8+ (works down to 3.6 with minor tweaks)
# No external dependencies. RTF save is basic; TXT is full-fidelity for plain text.

import os
import sys
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser

APP_NAME = "VistaPad AI"
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 11

# ---- AI Backend Contract ------------------------------------------------------
# Set AI_ENDPOINT to your LLM gateway. The app POSTs:
#   { "mode": "<summarize|continue|rewrite>", "text": "<input_text>", "system": "<optional>", "params": { ... } }
# Expect JSON response:
#   { "output": "<model_response>", "usage": { "prompt_tokens": int, "completion_tokens": int } }
# Replace the dummy requester to actually call your backend.
AI_ENDPOINT = os.environ.get("VISTAPAD_AI_ENDPOINT", "http://localhost:8000/llm")
AI_REQUEST_TIMEOUT = 30

# ---- Simple HTTP requester placeholder ---------------------------------------
# Replace this with 'requests.post' or your custom client. Kept offline-safe.
def ai_post(url, payload, timeout=AI_REQUEST_TIMEOUT):
    # Offline-safe stub. Provide a friendly, non-blocking fake response.
    # Swap this implementation with your real HTTP call.
    # Example real code:
    #   import requests
    #   r = requests.post(url, json=payload, timeout=timeout)
    #   r.raise_for_status()
    #   return r.json()
    text = payload.get("text", "")
    mode = payload.get("mode", "summarize")
    if mode == "summarize":
        out = "Summary: " + (text[:400] + ("..." if len(text) > 400 else ""))
    elif mode == "continue":
        out = text + "\n\n[AI] Continuing the text with a cohesive paragraph about your topic."
    elif mode == "rewrite":
        out = "Rewritten: " + text.replace("\n", " ").strip()
    else:
        out = "Unsupported mode."
    return {"output": out, "usage": {"prompt_tokens": len(text)//4, "completion_tokens": len(out)//4}}

# ---- Minimal RTF helpers (basic formatting only) ------------------------------
# Note: Tk Text isn’t rich-text aware; we export/import very basic RTF for bold/italic/underline only.
def export_rtf(text_widget):
    # Collect text and basic inline tags (b,i,u). Alignment, bullets, font sizes are not serialized fully.
    text = text_widget.get("1.0", "end-1c")
    # Tag spans
    # For simplicity, map three tags: "bold", "italic", "underline"
    spans = []
    for tag in ("bold", "italic", "underline"):
        ranges = text_widget.tag_ranges(tag)
        for i in range(0, len(ranges), 2):
            start = ranges[i]
            end = ranges[i+1]
            spans.append((tag, start, end))

    # Convert to RTF with naive control words.
    # RTF header with Segoe UI default
    rtf = ["{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Segoe UI;}}\\fs22 "]
    # We will walk character by character and open/close tags based on tag presence.
    def pos_to_index(idx):
        return tuple(map(int, str(idx).split(".")))  # (line, col)

    cur_tags = set()
    index = "1.0"
    end_index = text_widget.index("end-1c")

    def has_tag_at(tag, idx):
        return idx in text_widget.tag_ranges(tag)

    # Build tag map per index
    # For efficiency: we’ll step through characters and query text_widget.tag_names(index)
    while True:
        ch = text_widget.get(index)
        tags = set(text_widget.tag_names(index))
        # Close tags that are no longer present
        for t in list(cur_tags):
            if t not in tags:
                if t == "bold": rtf.append("\\b0 ")
                if t == "italic": rtf.append("\\i0 ")
                if t == "underline": rtf.append("\\ulnone ")
                cur_tags.remove(t)
        # Open tags newly present
        for t in tags:
            if t not in cur_tags and t in ("bold", "italic", "underline"):
                if t == "bold": rtf.append("\\b ")
                if t == "italic": rtf.append("\\i ")
                if t == "underline": rtf.append("\\ul ")
                cur_tags.add(t)
        # Escape RTF specials
        if ch == "\\":
            rtf.append("\\\\")
        elif ch == "{":
            rtf.append("\\{")
        elif ch == "}":
            rtf.append("\\}")
        elif ch == "\n":
            rtf.append("\\par ")
        else:
            rtf.append(ch)

        if index == end_index: break
        index = text_widget.index(f"{index} + 1c")

    # Close any open tags
    for t in list(cur_tags):
        if t == "bold": rtf.append("\\b0 ")
        if t == "italic": rtf.append("\\i0 ")
        if t == "underline": rtf.append("\\ulnone ")
    rtf.append("}")
    return "".join(rtf)

def import_rtf_to_text(text_widget, rtf_data):
    # Very naive: strip control words and insert plain text, then we don’t reconstruct tags.
    # If you want real RTF import, integrate a parser (e.g., PyRTF or your own).
    # For now, fall back to plain text extraction.
    # Extract text by removing braces and common control sequences.
    filtered = []
    i = 0
    while i < len(rtf_data):
        ch = rtf_data[i]
        if ch == "{":
            i += 1
            continue
        if ch == "}":
            i += 1
            continue
        if ch == "\\":
            # skip control word
            j = i + 1
            while j < len(rtf_data) and rtf_data[j].isalpha():
                j += 1
            # skip optional numeric
            while j < len(rtf_data) and rtf_data[j] in "-0123456789":
                j += 1
            # skip optional space
            if j < len(rtf_data) and rtf_data[j] == " ":
                j += 1
            # handle special \par
            # We won't attempt to reconstruct tags; insert newline for \par if desired
            i = j
            continue
        filtered.append(ch)
        i += 1
    text_widget.delete("1.0", "end")
    text_widget.insert("1.0", "".join(filtered))

# ---- Main application ---------------------------------------------------------
class VistaPadAI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x720")
        self.minsize(800, 500)
        self._file_path = None
        self._dirty = False
        self._dark = False
        self._autosave_path = os.path.join(os.path.expanduser("~"), ".vistapad_autosave.txt")
        self._status_msg = tk.StringVar(value="Ready")
        self._word_count = tk.StringVar(value="Words: 0")
        self._llm_busy = tk.BooleanVar(value=False)

        self._create_style()
        self._create_menu()
        self._create_ribbon()
        self._create_body()
        self._create_statusbar()
        self._bind_shortcuts()
        self._start_autosave()

    # ---- UI creation ----
    def _create_style(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("vista")
        except tk.TclError:
            self.style.theme_use("clam")
        # Vista-like hues
        self.style.configure("Ribbon.TFrame", background="#e6edf5")
        self.style.configure("Toolbar.TFrame", background="#dae3f0")
        self.style.configure("AI.TFrame", background="#f1f5fb")
        self.style.configure("Status.TFrame", background="#e8eef7")
        self.style.configure("TButton", padding=4)
        self.style.configure("TMenubutton", padding=4)
        self.style.configure("TNotebook", tabposition="n")

    def _create_menu(self):
        menubar = tk.Menu(self)
        # File
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New", accelerator="Ctrl+N", command=self.on_new)
        filem.add_command(label="Open...", accelerator="Ctrl+O", command=self.on_open)
        filem.add_command(label="Save", accelerator="Ctrl+S", command=self.on_save)
        filem.add_command(label="Save As...", command=self.on_save_as)
        filem.add_separator()
        filem.add_command(label="Page setup...", command=self.on_page_setup)  # placeholder
        filem.add_command(label="Print...", accelerator="Ctrl+P", command=self.on_print)
        filem.add_separator()
        filem.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=filem)

        # Edit
        editm = tk.Menu(menubar, tearoff=0)
        editm.add_command(label="Undo", accelerator="Ctrl+Z", command=lambda: self.text.event_generate("<<Undo>>"))
        editm.add_command(label="Redo", accelerator="Ctrl+Y", command=lambda: self.text.event_generate("<<Redo>>"))
        editm.add_separator()
        editm.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: self.text.event_generate("<<Cut>>"))
        editm.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self.text.event_generate("<<Copy>>"))
        editm.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: self.text.event_generate("<<Paste>>"))
        editm.add_separator()
        editm.add_command(label="Find/Replace", accelerator="Ctrl+F", command=self.on_find_replace)
        editm.add_command(label="Select All", accelerator="Ctrl+A", command=lambda: self.text.tag_add("sel", "1.0", "end-1c"))
        menubar.add_cascade(label="Edit", menu=editm)

        # Format
        formatm = tk.Menu(menubar, tearoff=0)
        formatm.add_command(label="Font...", command=self.on_font_dialog)
        formatm.add_command(label="Text color...", command=self.on_text_color)
        formatm.add_command(label="Highlight...", command=self.on_text_bg)
        menubar.add_cascade(label="Format", menu=formatm)

        # View
        viewm = tk.Menu(menubar, tearoff=0)
        viewm.add_checkbutton(label="Dark mode", command=self.toggle_dark)
        menubar.add_cascade(label="View", menu=viewm)

        # Help
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="About VistaPad AI", command=lambda: messagebox.showinfo(APP_NAME, f"{APP_NAME}\nA Vista-style WordPad with AI panel.\nSingle-file Tkinter app."))
        menubar.add_cascade(label="Help", menu=helpm)

        self.config(menu=menubar)

    def _create_ribbon(self):
        ribbon = ttk.Frame(self, style="Ribbon.TFrame")
        ribbon.pack(side="top", fill="x")

        # Font family and size
        tb = ttk.Frame(ribbon, style="Toolbar.TFrame")
        tb.pack(side="left", padx=8, pady=6)

        self.font_family = tk.StringVar(value=DEFAULT_FONT_FAMILY)
        self.font_size = tk.IntVar(value=DEFAULT_FONT_SIZE)

        font_box = ttk.Combobox(tb, textvariable=self.font_family, width=16, state="readonly",
                                values=self._list_fonts())
        font_box.pack(side="left", padx=4)
        size_box = ttk.Combobox(tb, textvariable=self.font_size, width=4, state="readonly",
                                values=[8,9,10,11,12,14,16,18,20,22,24,28,32,36])
        size_box.pack(side="left", padx=4)
        font_box.bind("<<ComboboxSelected>>", lambda e: self.apply_font())
        size_box.bind("<<ComboboxSelected>>", lambda e: self.apply_font())

        # Bold/Italic/Underline
        ttk.Button(tb, text="B", width=3, command=lambda: self.toggle_tag("bold")).pack(side="left", padx=2)
        ttk.Button(tb, text="I", width=3, command=lambda: self.toggle_tag("italic")).pack(side="left", padx=2)
        ttk.Button(tb, text="U", width=3, command=lambda: self.toggle_tag("underline")).pack(side="left", padx=2)

        # Alignments
        ttk.Button(tb, text="Left", command=lambda: self.set_align("left")).pack(side="left", padx=4)
        ttk.Button(tb, text="Center", command=lambda: self.set_align("center")).pack(side="left", padx=4)
        ttk.Button(tb, text="Right", command=lambda: self.set_align("right")).pack(side="left", padx=4)

        # Bullets
        ttk.Button(tb, text="• Bullet", command=self.insert_bullet).pack(side="left", padx=8)

        # Colors
        ttk.Button(tb, text="Text color", command=self.on_text_color).pack(side="left", padx=4)
        ttk.Button(tb, text="Highlight", command=self.on_text_bg).pack(side="left", padx=4)

        # Quick actions
        ttk.Button(tb, text="Clear formatting", command=self.clear_formatting).pack(side="left", padx=8)
        ttk.Button(tb, text="Word count", command=self.update_word_count).pack(side="left", padx=4)

    def _create_body(self):
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Notebook (Editor + AI)
        nb = ttk.Notebook(body)
        nb.pack(fill="both", expand=True)

        # Editor tab
        editor_tab = ttk.Frame(nb)
        nb.add(editor_tab, text="Document")

        # AI tab
        ai_tab = ttk.Frame(nb, style="AI.TFrame")
        nb.add(ai_tab, text="AI Assistant")

        # Text editor with scrollbar
        text_frame = ttk.Frame(editor_tab)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", undo=True, maxundo=-1)
        self.text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(text_frame, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.config(yscrollcommand=scroll.set)

        # Setup tags
        self.text.tag_configure("bold", font=(DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE, "bold"))
        self.text.tag_configure("italic", font=(DEFAULT_FONT_FAMILY, DEFAULT_FONT_SIZE, "italic"))
        self.text.tag_configure("underline", underline=1)
        self.text.tag_configure("left", justify="left")
        self.text.tag_configure("center", justify="center")
        self.text.tag_configure("right", justify="right")
        self.text.tag_configure("highlight", background="#fff8a5")
        self.text.tag_configure("color", foreground="#333")

        # Track changes
        self.text.bind("<<Modified>>", self._on_modified)

        # AI panel content
        ai_top = ttk.Frame(ai_tab, padding=10)
        ai_top.pack(fill="x")
        ttk.Label(ai_top, text="AI mode:").pack(side="left")
        self.ai_mode = tk.StringVar(value="summarize")
        ttk.Combobox(ai_top, textvariable=self.ai_mode, state="readonly",
                     values=["summarize", "continue", "rewrite"], width=12).pack(side="left", padx=6)

        ttk.Button(ai_top, text="Run", command=self.on_ai_run).pack(side="left", padx=6)
        self.ai_status = ttk.Label(ai_top, textvariable=self._status_msg)
        self.ai_status.pack(side="right")

        ai_mid = ttk.Frame(ai_tab, padding=10)
        ai_mid.pack(fill="both", expand=True)
        ttk.Label(ai_mid, text="Prompt / system note (optional):").pack(anchor="w")
        self.ai_prompt = tk.Text(ai_mid, height=6, wrap="word")
        self.ai_prompt.pack(fill="x", pady=6)

        ttk.Label(ai_mid, text="AI output:").pack(anchor="w", pady=(6,0))
        self.ai_output = tk.Text(ai_mid, height=10, wrap="word")
        self.ai_output.pack(fill="both", expand=True, pady=(4,10))

    def _create_statusbar(self):
        status = ttk.Frame(self, style="Status.TFrame")
        status.pack(side="bottom", fill="x")
        ttk.Label(status, textvariable=self._status_msg).pack(side="left", padx=10)
        ttk.Label(status, textvariable=self._word_count).pack(side="right", padx=10)

    # ---- Behaviors ----
    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.on_new())
        self.bind("<Control-o>", lambda e: self.on_open())
        self.bind("<Control-s>", lambda e: self.on_save())
        self.bind("<Control-p>", lambda e: self.on_print())
        self.bind("<Control-f>", lambda e: self.on_find_replace())
        self.bind("<Control-a>", lambda e: self.text.tag_add("sel", "1.0", "end-1c"))
        self.text.bind("<KeyRelease>", lambda e: self.update_word_count())

    def _start_autosave(self):
        def autosave_loop():
            while True:
                time.sleep(15)
                try:
                    content = self.text.get("1.0", "end-1c")
                    with open(self._autosave_path, "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass
        t = threading.Thread(target=autosave_loop, daemon=True)
        t.start()

    def _list_fonts(self):
        # Prefer system defaults
        return [DEFAULT_FONT_FAMILY, "Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Tahoma", "Times New Roman", "Verdana"]

    def _on_modified(self, event):
        self._dirty = bool(self.text.edit_modified())
        self.text.edit_modified(False)
        self.update_word_count()
        self._status_msg.set("Modified" if self._dirty else "Ready")

    def update_word_count(self):
        text = self.text.get("1.0", "end-1c")
        words = [w for w in text.split() if w.strip()]
        self._word_count.set(f"Words: {len(words)}")

    # ---- File ops ----
    def on_new(self):
        if not self._confirm_discard(): return
        self.text.delete("1.0", "end")
        self._file_path = None
        self._dirty = False
        self._status_msg.set("New document")
        self.update_word_count()

    def on_open(self):
        path = filedialog.askopenfilename(title="Open", filetypes=[("Text", "*.txt"), ("Rich Text", "*.rtf"), ("All files", "*.*")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
            if path.lower().endswith(".rtf"):
                import_rtf_to_text(self.text, data)
            else:
                self.text.delete("1.0", "end")
                self.text.insert("1.0", data)
            self._file_path = path
            self._dirty = False
            self._status_msg.set(f"Opened: {os.path.basename(path)}")
            self.update_word_count()
        except Exception as e:
            messagebox.showerror("Open error", str(e))

    def on_save(self):
        if not self._file_path:
            return self.on_save_as()
        try:
            if self._file_path.lower().endswith(".rtf"):
                data = export_rtf(self.text)
            else:
                data = self.text.get("1.0", "end-1c")
            with open(self._file_path, "w", encoding="utf-8") as f:
                f.write(data)
            self._dirty = False
            self._status_msg.set(f"Saved: {os.path.basename(self._file_path)}")
        except Exception as e:
            messagebox.showerror("Save error", str(e))

    def on_save_as(self):
        path = filedialog.asksaveasfilename(title="Save As", defaultextension=".txt",
                                            filetypes=[("Text", "*.txt"), ("Rich Text", "*.rtf")])
        if not path: return
        self._file_path = path
        self.on_save()

    def on_page_setup(self):
        messagebox.showinfo("Page setup", "Page setup is not implemented in this demo.")

    def on_print(self):
        try:
            # Windows: write to temp file and open print dialog via default app
            import tempfile
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
            tmp.write(self.text.get("1.0", "end-1c"))
            tmp.close()
            os.startfile(tmp.name, "print")
            self._status_msg.set("Sent to printer")
        except Exception as e:
            messagebox.showerror("Print error", str(e))

    def on_exit(self):
        if not self._confirm_discard(): return
        self.destroy()

    def _confirm_discard(self):
        if self._dirty:
            return messagebox.askyesno(APP_NAME, "Discard unsaved changes?")
        return True

    # ---- Formatting ----
    def apply_font(self):
        family = self.font_family.get()
        size = self.font_size.get()
        self.text.configure(font=(family, size))
        # Update basic tag fonts
        self.text.tag_configure("bold", font=(family, size, "bold"))
        self.text.tag_configure("italic", font=(family, size, "italic"))

    def toggle_tag(self, tag):
        try:
            start, end = self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return
        if tag in self.text.tag_names("sel.first"):
            self.text.tag_remove(tag, start, end)
        else:
            self.text.tag_add(tag, start, end)

    def set_align(self, align):
        try:
            start, end = self.text.index("sel.first linestart"), self.text.index("sel.last lineend")
        except tk.TclError:
            return
        self.text.tag_remove("left", start, end)
        self.text.tag_remove("center", start, end)
        self.text.tag_remove("right", start, end)
        self.text.tag_add(align, start, end)

    def insert_bullet(self):
        try:
            start = self.text.index("insert linestart")
            self.text.insert(start, u"\u2022 ")
        except tk.TclError:
            pass

    def clear_formatting(self):
        self.text.tag_remove("bold", "1.0", "end")
        self.text.tag_remove("italic", "1.0", "end")
        self.text.tag_remove("underline", "1.0", "end")
        self.text.tag_remove("left", "1.0", "end")
        self.text.tag_remove("center", "1.0", "end")
        self.text.tag_remove("right", "1.0", "end")
        self.text.tag_remove("highlight", "1.0", "end")
        self.text.tag_remove("color", "1.0", "end")
        self._status_msg.set("Formatting cleared")

    def on_text_color(self):
        color = colorchooser.askcolor()[1]
        if not color: return
        try:
            start, end = self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return
        self.text.tag_configure("color", foreground=color)
        self.text.tag_add("color", start, end)

    def on_text_bg(self):
        color = colorchooser.askcolor()[1]
        if not color: return
        try:
            start, end = self.text.index("sel.first"), self.text.index("sel.last")
        except tk.TclError:
            return
        self.text.tag_configure("highlight", background=color)
        self.text.tag_add("highlight", start, end)

    def on_font_dialog(self):
        # Minimal font dialog: prompt for size
        size = simpledialog.askinteger("Font size", "Enter font size:", initialvalue=self.font_size.get(), minvalue=6, maxvalue=72)
        if size:
            self.font_size.set(size)
            self.apply_font()

    def on_find_replace(self):
        dlg = tk.Toplevel(self)
        dlg.title("Find/Replace")
        dlg.geometry("360x180")
        ttk.Label(dlg, text="Find:").pack(anchor="w", padx=10, pady=(10,0))
        find_var = tk.StringVar()
        find_entry = ttk.Entry(dlg, textvariable=find_var)
        find_entry.pack(fill="x", padx=10)
        ttk.Label(dlg, text="Replace:").pack(anchor="w", padx=10, pady=(10,0))
        repl_var = tk.StringVar()
        repl_entry = ttk.Entry(dlg, textvariable=repl_var)
        repl_entry.pack(fill="x", padx=10, pady=(0,10))

        btns = ttk.Frame(dlg)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="Find next", command=lambda: self._find_next(find_var.get())).pack(side="left", padx=4)
        ttk.Button(btns, text="Replace", command=lambda: self._replace(find_var.get(), repl_var.get())).pack(side="left", padx=4)
        ttk.Button(btns, text="Replace all", command=lambda: self._replace_all(find_var.get(), repl_var.get())).pack(side="left", padx=4)

    def _find_next(self, needle):
        self.text.tag_remove("found", "1.0", "end")
        if not needle: return
        pos = self.text.search(needle, "insert", nocase=True, stopindex="end")
        if pos:
            end = f"{pos}+{len(needle)}c"
            self.text.tag_add("found", pos, end)
            self.text.tag_configure("found", background="#a1d6ff")
            self.text.mark_set("insert", end)
            self.text.see(pos)

    def _replace(self, needle, repl):
        if not needle: return
        pos = self.text.search(needle, "insert", nocase=True, stopindex="end")
        if pos:
            end = f"{pos}+{len(needle)}c"
            self.text.delete(pos, end)
            self.text.insert(pos, repl)
            self.text.mark_set("insert", f"{pos}+{len(repl)}c")

    def _replace_all(self, needle, repl):
        if not needle: return
        start = "1.0"
        while True:
            pos = self.text.search(needle, start, nocase=True, stopindex="end")
            if not pos: break
            end = f"{pos}+{len(needle)}c"
            self.text.delete(pos, end)
            self.text.insert(pos, repl)
            start = f"{pos}+{len(repl)}c"

    # ---- Dark mode ----
    def toggle_dark(self):
        self._dark = not self._dark
        bg = "#1e1e1e" if self._dark else "white"
        fg = "#e6e6e6" if self._dark else "black"
        self.text.configure(bg=bg, fg=fg, insertbackground=fg)
        self.ai_output.configure(bg=bg, fg=fg, insertbackground=fg)
        self.ai_prompt.configure(bg=bg, fg=fg, insertbackground=fg)
        self._status_msg.set("Dark mode ON" if self._dark else "Dark mode OFF")

    # ---- AI actions ----
    def on_ai_run(self):
        if self._llm_busy.get(): return
        mode = self.ai_mode.get()
        # Input selection preference for rewrite; otherwise whole doc
        try:
            sel_text = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            sel_text = ""
        doc_text = self.text.get("1.0", "end-1c")
        input_text = sel_text if (mode == "rewrite" and sel_text.strip()) else doc_text
        sys_note = self.ai_prompt.get("1.0", "end-1c").strip()

        payload = {"mode": mode, "text": input_text, "system": sys_note, "params": {"temperature": 0.7}}
        self._status_msg.set("AI running...")
        self._llm_busy.set(True)

        def worker():
            try:
                resp = ai_post(AI_ENDPOINT, payload, timeout=AI_REQUEST_TIMEOUT)
                out = resp.get("output", "")
                usage = resp.get("usage", {})
                self.ai_output.delete("1.0", "end")
                self.ai_output.insert("1.0", out)
                # If rewrite with selection, replace in doc
                if mode == "rewrite" and sel_text.strip():
                    try:
                        self.text.delete("sel.first", "sel.last")
                        self.text.insert("insert", out)
                    except tk.TclError:
                        pass
                self._status_msg.set(f"AI done. Tokens: {usage.get('prompt_tokens', 0)}/{usage.get('completion_tokens', 0)}")
            except Exception as e:
                self.ai_output.delete("1.0", "end")
                self.ai_output.insert("1.0", f"AI error: {e}")
                self._status_msg.set("AI error")
            finally:
                self._llm_busy.set(False)

        threading.Thread(target=worker, daemon=True).start()

# ---- Entry point ----
def main():
    app = VistaPadAI()
    # Load autosave if present
    try:
        if os.path.exists(app._autosave_path) and os.path.getsize(app._autosave_path) > 0:
            with open(app._autosave_path, "r", encoding="utf-8") as f:
                app.text.insert("1.0", f.read())
            app._status_msg.set("Recovered autosave")
            app.update_word_count()
    except Exception:
        pass
    app.mainloop()

if __name__ == "__main__":
    main()
