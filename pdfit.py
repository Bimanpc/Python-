import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import PyPDF2
import openai

# 🔑 Set your API key here (or use environment variable)
openai.api_key = "YOUR_OPENAI_API_KEY"

class PDFReaderAI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI PDF Reader")
        self.pdf_text = ""

        # Buttons
        tk.Button(root, text="Open PDF", command=self.open_pdf).pack(pady=5)
        tk.Button(root, text="Ask AI", command=self.ask_ai).pack(pady=5)

        # PDF text display
        self.text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=80, height=20)
        self.text_area.pack(padx=10, pady=10)

        # AI response display
        self.response_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=80, height=10, fg="blue")
        self.response_area.pack(padx=10, pady=10)

    def open_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if not file_path:
            return
        try:
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                self.pdf_text = ""
                for page in reader.pages:
                    self.pdf_text += page.extract_text() + "\n"
            self.text_area.delete(1.0, tk.END)
            self.text_area.insert(tk.END, self.pdf_text)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read PDF: {e}")

    def ask_ai(self):
        user_input = self.text_area.get(tk.SEL_FIRST, tk.SEL_LAST) if self.text_area.tag_ranges(tk.SEL) else self.text_area.get(1.0, tk.END)
        if not user_input.strip():
            messagebox.showwarning("Warning", "No text selected or available.")
            return

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",  # or "gpt-4o", "gpt-3.5-turbo"
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes and explains PDF content."},
                    {"role": "user", "content": user_input}
                ],
                max_tokens=500
            )
            ai_text = response["choices"][0]["message"]["content"]
            self.response_area.delete(1.0, tk.END)
            self.response_area.insert(tk.END, ai_text)
        except Exception as e:
            messagebox.showerror("Error", f"AI request failed: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFReaderAI(root)
    root.mainloop()
