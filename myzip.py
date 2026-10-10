import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import zipfile
import os

class ZipArchiver:
    def __init__(self, root):
        self.root = root
        self.root.title("ZIP GUI Archiver")
        self.root.geometry("700x500")

        self.files = []

        title = tk.Label(
            root,
            text="ZIP GUI Archiver",
            font=("Segoe UI", 18, "bold")
        )
        title.pack(pady=10)

        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)

        self.listbox = tk.Listbox(frame)
        self.listbox.pack(fill="both", expand=True, side="left")

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.listbox.yview)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame,
            text="Προσθήκη Αρχείων",
            command=self.add_files,
            width=20
        ).grid(row=0, column=0, padx=5)

        tk.Button(
            btn_frame,
            text="Αφαίρεση Επιλεγμένου",
            command=self.remove_file,
            width=20
        ).grid(row=0, column=1, padx=5)

        tk.Button(
            btn_frame,
            text="Δημιουργία ZIP",
            command=self.create_zip,
            width=20
        ).grid(row=0, column=2, padx=5)

        self.progress = ttk.Progressbar(
            root,
            orient="horizontal",
            length=600,
            mode="determinate"
        )
        self.progress.pack(pady=20)

        self.status = tk.Label(root, text="Έτοιμο")
        self.status.pack()

    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Επιλογή Αρχείων"
        )

        for file in files:
            if file not in self.files:
                self.files.append(file)
                self.listbox.insert(tk.END, file)

    def remove_file(self):
        selected = self.listbox.curselection()

        if selected:
            index = selected[0]
            self.listbox.delete(index)
            self.files.pop(index)

    def create_zip(self):
        if not self.files:
            messagebox.showwarning(
                "Προσοχή",
                "Δεν υπάρχουν αρχεία."
            )
            return

        zip_name = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP Files", "*.zip")]
        )

        if not zip_name:
            return

        try:
            self.progress["value"] = 0
            self.progress["maximum"] = len(self.files)

            with zipfile.ZipFile(
                zip_name,
                "w",
                zipfile.ZIP_DEFLATED
            ) as zipf:

                for i, file in enumerate(self.files):
                    zipf.write(
                        file,
                        arcname=os.path.basename(file)
                    )

                    self.progress["value"] = i + 1
                    self.status.config(
                        text=f"Συμπίεση: {os.path.basename(file)}"
                    )
                    self.root.update_idletasks()

            self.status.config(text="Ολοκληρώθηκε")
            messagebox.showinfo(
                "Επιτυχία",
                "Το ZIP δημιουργήθηκε επιτυχώς."
            )

        except Exception as e:
            messagebox.showerror(
                "Σφάλμα",
                str(e)
            )

if __name__ == "__main__":
    root = tk.Tk()
    app = ZipArchiver(root)
    root.mainloop()
