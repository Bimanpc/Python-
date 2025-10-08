import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime

class ChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Viber-like Chat App")
        self.root.geometry("400x500")
        self.root.configure(bg="#665CAC")  # Viber purple

        # Chat display area
        self.chat_area = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, state="disabled", 
            bg="#f5f5f5", fg="black", font=("Arial", 11)
        )
        self.chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Message entry box
        self.entry_frame = tk.Frame(root, bg="#ddd")
        self.entry_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.msg_entry = tk.Entry(
            self.entry_frame, font=("Arial", 12)
        )
        self.msg_entry.pack(side=tk.LEFT, padx=5, pady=5, fill=tk.X, expand=True)
        self.msg_entry.bind("<Return>", self.send_message)

        self.send_btn = tk.Button(
            self.entry_frame, text="Send", command=self.send_message,
            bg="#665CAC", fg="white", font=("Arial", 10, "bold")
        )
        self.send_btn.pack(side=tk.RIGHT, padx=5, pady=5)

    def send_message(self, event=None):
        msg = self.msg_entry.get().strip()
        if msg:
            self.display_message("You", msg, "blue")
            # Simulate a reply
            self.root.after(1000, lambda: self.display_message("Friend", "Got it!", "green"))
            self.msg_entry.delete(0, tk.END)

    def display_message(self, sender, msg, color):
        self.chat_area.config(state="normal")
        timestamp = datetime.now().strftime("%H:%M")
        self.chat_area.insert(tk.END, f"{sender} ({timestamp}):\n", ("bold",))
        self.chat_area.insert(tk.END, f"{msg}\n\n", (color,))
        self.chat_area.tag_config("bold", font=("Arial", 10, "bold"))
        self.chat_area.tag_config("blue", foreground="blue")
        self.chat_area.tag_config("green", foreground="darkgreen")
        self.chat_area.config(state="disabled")
        self.chat_area.yview(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatApp(root)
    root.mainloop()
