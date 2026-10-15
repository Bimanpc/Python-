
#!/usr/bin/env python3
"""
FreeBSD Notepad
A lightweight desktop text editor built with Python and Tkinter.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import os


class FreeBSDNotepad:
    def __init__(self, root):
        self.root = root
        self.filename = None
        self.modified = False

        self.root.title("FreeBSD Notepad")
        self.root.geometry("900x600")
        self.root.configure(bg="#252525")

        self.create_menu()
        self.create_editor()
        self.create_statusbar()

        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

    def create_menu(self):
        menu = tk.Menu(self.root)

        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="New", command=self.new_file,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self.open_file,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.exit_app)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=0)
        edit_menu.add_command(label="Undo", command=self.undo)
        edit_menu.add_command(label="Cut", command=self.cut)
        edit_menu.add_command(label="Copy", command=self.copy)
        edit_menu.add_command(label="Paste", command=self.paste)
        edit_menu.add_command(label="Find...", command=self.find_text)
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All", command=self.select_all)
        menu.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=0)
        view_menu.add_command(label="Dark Theme", command=self.dark_theme)
        view_menu.add_command(label="Light Theme", command=self.light_theme)
        menu.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About", command=self.about)
        menu.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menu)

        self.root.bind("<Control-n>", lambda e: self.new_file())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_file())

    def create_editor(self):
        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.text = tk.Text(
            frame,
            wrap=tk.NONE,
            undo=True,
            font=("DejaVu Sans Mono", 11),
            bg="#171717",
            fg="#eeeeee",
            insertbackground="white",
            selectbackground="#365f91",
            padx=10,
            pady=10
        )

        y_scroll = tk.Scrollbar(frame, command=self.text.yview)
        x_scroll = tk.Scrollbar(
            frame, orient=tk.HORIZONTAL, command=self.text.xview
        )

        self.text.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set
        )

        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.text.bind("<<Modified>>", self.on_modified)
        self.text.bind("<KeyRelease>", self.update_status)
        self.text.bind("<ButtonRelease>", self.update_status)

    def create_statusbar(self):
        self.status = tk.Label(
            self.root,
            text="Ready | FreeBSD Notepad",
            anchor="w",
            bg="#303030",
            fg="white",
            padx=8,
            pady=5
        )
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def on_modified(self, event=None):
        if self.text.edit_modified():
            self.modified = True
            self.update_title()
            self.text.edit_modified(False)

    def update_title(self):
        name = os.path.basename(self.filename) if self.filename else "Untitled"
        marker = "*" if self.modified else ""
        self.root.title(f"{marker}{name} - FreeBSD Notepad")

    def update_status(self, event=None):
        line, column = self.text.index(tk.INSERT).split(".")
        self.status.config(
            text=f"Line: {line} | Column: {int(column) + 1} | "
                 f"{'Modified' if self.modified else 'Saved'}"
        )

    def confirm_changes(self):
        if not self.modified:
            return True

        answer = messagebox.askyesnocancel(
            "Unsaved Changes",
            "Save changes before continuing?"
        )

        if answer is None:
            return False
        if answer:
            return self.save_file()
        return True

    def new_file(self):
        if not self.confirm_changes():
            return
        self.text.delete("1.0", tk.END)
        self.filename = None
        self.modified = False
        self.text.edit_modified(False)
        self.update_title()
        self.update_status()

    def open_file(self):
        if not self.confirm_changes():
            return

        path = filedialog.askopenfilename(
            title="Open Text File",
            filetypes=[
                ("Text files", "*.txt *.md *.py *.sh *.conf *.log"),
                ("All files", "*.*")
            ]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as file:
                content = file.read()
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", content)
            self.filename = path
            self.modified = False
            self.text.edit_modified(False)
            self.update_title()
            self.update_status()
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Open Error", str(error))

    def save_file(self):
        if not self.filename:
            return self.save_as()

        try:
            with open(self.filename, "w", encoding="utf-8") as file:
                file.write(self.text.get("1.0", "end-1c"))
            self.modified = False
            self.text.edit_modified(False)
            self.update_title()
            self.update_status()
            return True
        except OSError as error:
            messagebox.showerror("Save Error", str(error))
            return False

    def save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save Text File",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("Python files", "*.py"),
                ("Shell scripts", "*.sh"),
                ("All files", "*.*")
            ]
        )
        if not path:
            return False

        previous = self.filename
        self.filename = path
        if not self.save_file():
            self.filename = previous
            self.update_title()
            return False
        return True

    def find_text(self):
        query = simpledialog.askstring("Find", "Enter text to find:")
        if not query:
            return

        self.text.tag_remove("found", "1.0", tk.END)
        start = "1.0"
        count = 0

        while True:
            pos = self.text.search(
                query, start, stopindex=tk.END, nocase=True
            )
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            self.text.tag_add("found", pos, end)
            start = end
            count += 1

        self.text.tag_config(
            "found", background="#e6c84f", foreground="black"
        )
        self.status.config(text=f"Found {count} match(es)")

    def undo(self):
        try:
            self.text.edit_undo()
        except tk.TclError:
            pass

    def cut(self):
        self.text.event_generate("<<Cut>>")

    def copy(self):
        self.text.event_generate("<<Copy>>")

    def paste(self):
        self.text.event_generate("<<Paste>>")

    def select_all(self):
        self.text.tag_add("sel", "1.0", tk.END)
        return "break"

    def dark_theme(self):
        self.text.configure(
            bg="#171717", fg="#eeeeee", insertbackground="white"
        )
        self.text.tag_config("found", background="#e6c84f", foreground="black")

    def light_theme(self):
        self.text.configure(
            bg="white", fg="black", insertbackground="black"
        )
        self.text.tag_config("found", background="yellow", foreground="black")

    def about(self):
        messagebox.showinfo(
            "About FreeBSD Notepad",
            "FreeBSD Notepad 1.0\n"
            "A simple Python and Tkinter text editor.\n"
            "Designed for FreeBSD and other Unix-like systems."
        )

    def exit_app(self):
        if self.confirm_changes():
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = FreeBSDNotepad(root)
    root.mainloop()
