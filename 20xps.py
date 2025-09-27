import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from PIL import Image, ImageTk

import fitz  # PyMuPDF
from openai import OpenAI

APP_TITLE = "AI XPS Viewer"
DEFAULT_ZOOM = 1.25  # initial zoom factor

class XPSViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.doc = None
        self.page_index = 0
        self.zoom = DEFAULT_ZOOM
        self.photo = None
        self.canvas_image_id = None
        self.client = None

        self._build_ui()
        self._init_ai_client()

    def _build_ui(self):
        self.root.geometry("1000x700")

        # Top toolbar
        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self.open_btn = ttk.Button(toolbar, text="Open XPS", command=self.open_file)
        self.open_btn.pack(side=tk.LEFT)

        self.prev_btn = ttk.Button(toolbar, text="Prev", command=self.prev_page, state=tk.DISABLED)
        self.prev_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.next_btn = ttk.Button(toolbar, text="Next", command=self.next_page, state=tk.DISABLED)
        self.next_btn.pack(side=tk.LEFT)

        self.zoom_out_btn = ttk.Button(toolbar, text="− Zoom", command=self.zoom_out, state=tk.DISABLED)
        self.zoom_out_btn.pack(side=tk.LEFT, padx=(16, 0))

        self.zoom_in_btn = ttk.Button(toolbar, text="+ Zoom", command=self.zoom_in, state=tk.DISABLED)
        self.zoom_in_btn.pack(side=tk.LEFT)

        self.page_label = ttk.Label(toolbar, text="Page: —/—")
        self.page_label.pack(side=tk.LEFT, padx=(16, 0))

        # AI controls
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        self.summary_pages_entry = ttk.Entry(toolbar, width=10)
        self.summary_pages_entry.insert(0, "1-3")  # default summary range
        self.summary_pages_entry.pack(side=tk.LEFT)
        ttk.Label(toolbar, text="Pages to summarize").pack(side=tk.LEFT, padx=(6, 0))
        self.summary_btn = ttk.Button(toolbar, text="Summarize", command=self.summarize_doc, state=tk.DISABLED)
        self.summary_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Viewer canvas with scrollbars
        viewer_frame = ttk.Frame(self.root)
        viewer_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(viewer_frame, bg="#1e1e1e")
        self.h_scroll = ttk.Scrollbar(viewer_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(viewer_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        viewer_frame.rowconfigure(0, weight=1)
        viewer_frame.columnconfigure(0, weight=1)

        # AI output
        ai_frame = ttk.LabelFrame(self.root, text="AI summary", padding=6)
        ai_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.ai_text = tk.Text(ai_frame, height=10, wrap=tk.WORD)
        self.ai_text.pack(fill=tk.X)

        # Bind mouse wheel for zoom (Ctrl + wheel)
        self.canvas.bind("<Control-MouseWheel>", self._mouse_zoom)

    def _init_ai_client(self):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception as e:
                self._log_ai(f"AI init error: {e}")
        else:
            self._log_ai("Set OPENAI_API_KEY environment variable to enable AI summaries.")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open XPS file",
            filetypes=[("XPS files", "*.xps"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            doc = fitz.open(path)
            if doc.page_count == 0:
                raise ValueError("No pages found")
            self.doc = doc
            self.page_index = 0
            self.zoom = DEFAULT_ZOOM
            self._update_controls()
            self.render_page()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open XPS: {e}")

    def _update_controls(self):
        has_doc = self.doc is not None
        self.prev_btn.config(state=(tk.NORMAL if has_doc and self.page_index > 0 else tk.DISABLED))
        self.next_btn.config(state=(tk.NORMAL if has_doc and self.page_index < self.doc.page_count - 1 else tk.DISABLED))
        self.zoom_in_btn.config(state=(tk.NORMAL if has_doc else tk.DISABLED))
        self.zoom_out_btn.config(state=(tk.NORMAL if has_doc else tk.DISABLED))
        self.summary_btn.config(state=(tk.NORMAL if has_doc and self.client else tk.DISABLED))
        if has_doc:
            self.page_label.config(text=f"Page: {self.page_index + 1}/{self.doc.page_count}")
        else:
            self.page_label.config(text="Page: —/—")

    def render_page(self):
        if not self.doc:
            return
        try:
            page = self.doc.load_page(self.page_index)
            mat = fitz.Matrix(self.zoom, self.zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas_image_id = self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW)
            self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
            self._update_controls()
        except Exception as e:
            messagebox.showerror("Render error", f"Could not render page: {e}")

    def next_page(self):
        if self.doc and self.page_index < self.doc.page_count - 1:
            self.page_index += 1
            self.render_page()

    def prev_page(self):
        if self.doc and self.page_index > 0:
            self.page_index -= 1
            self.render_page()

    def zoom_in(self):
        if self.doc:
            self.zoom = min(self.zoom * 1.2, 6.0)
            self.render_page()

    def zoom_out(self):
        if self.doc:
            self.zoom = max(self.zoom / 1.2, 0.25)
            self.render_page()

    def _mouse_zoom(self, event):
        if not self.doc:
            return
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def summarize_doc(self):
        if not self.client or not self.doc:
            self._log_ai("AI client not initialized or document not loaded.")
            return

        pages_range = self.summary_pages_entry.get().strip()
        try:
            pages = self._parse_pages_range(pages_range)
        except ValueError as e:
            messagebox.showwarning("Invalid range", str(e))
            return

        text = self._extract_text(pages)
        if not text.strip():
            self._log_ai("No extractable text found in selected pages.")
            return

        prompt = (
            "Summarize the following XPS document content for a technical audience. "
            "Highlight key points, structure, any action items, and notable figures.\n\n"
            f"{text[:20000]}"  # guard token cost; limit to ~20k chars
        )

        self.summary_btn.config(state=tk.DISABLED)
        self._log_ai("Summarizing...")

        def run():
            try:
                # Using Responses API for a concise summary
                resp = self.client.responses.create(
                    model="gpt-4o-mini",
                    input=prompt
                )
                output = resp.output_text
                self._set_ai_text(output.strip())
            except Exception as e:
                self._log_ai(f"AI error: {e}")
            finally:
                self.summary_btn.config(state=tk.NORMAL)

        threading.Thread(target=run, daemon=True).start()

    def _extract_text(self, pages):
        chunks = []
        for i in pages:
            try:
                page = self.doc.load_page(i)
                chunks.append(page.get_text("text"))
            except Exception:
                # skip problematic page
                continue
        return "\n\n".join(chunks)

    def _parse_pages_range(self, s):
        """
        Parse a range like '1-3,5,7-8' into zero-based page indices.
        """
        if not self.doc:
            raise ValueError("No document")
        total = self.doc.page_count
        s = s.replace(" ", "")
        result = set()
        if not s:
            return list(range(total))
        for part in s.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                if not a.isdigit() or not b.isdigit():
                    raise ValueError("Ranges must be numbers like 1-3")
                start = max(1, int(a))
                end = min(total, int(b))
                if start > end:
                    raise ValueError("Range start must be <= end")
                for x in range(start, end + 1):
                    result.add(x - 1)
            else:
                if not part.isdigit():
                    raise ValueError("Page numbers must be numeric")
                x = int(part)
                if not (1 <= x <= total):
                    raise ValueError(f"Page {x} out of bounds (1-{total})")
                result.add(x - 1)
        return sorted(result)

    def _log_ai(self, msg):
        self.ai_text.insert(tk.END, msg + "\n")
        self.ai_text.see(tk.END)

    def _set_ai_text(self, txt):
        self.ai_text.delete("1.0", tk.END)
        self.ai_text.insert(tk.END, txt)
        self.ai_text.see(tk.END)

def main():
    root = tk.Tk()
    # Use the native theme on Windows if available
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    app = XPSViewerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
