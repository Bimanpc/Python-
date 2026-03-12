# ai_pdf_editor.py
import os
import requests
from pymupdf4llm import convert_pdf_to_markdown
import markdown2
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

LLM_API_URL = os.getenv("LLM_API_URL")  # e.g., OpenAI or local LLM endpoint
LLM_API_KEY = os.getenv("LLM_API_KEY")

def ask_llm(prompt: str) -> str:
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    payload = {"model":"gpt-4o-mini","input": prompt}  # adapt to your LLM API
    r = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["output_text"]  # adapt to your API's response shape

def pdf_to_markdown(path: str) -> str:
    md = convert_pdf_to_markdown(path)  # returns Markdown string
    return md

def markdown_to_pdf(md: str, out_path: str):
    html = markdown2.markdown(md)
    # Simple renderer: draw text lines on pages (for complex layout use weasyprint)
    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    y = height - 40
    for line in html.splitlines():
        if y < 40:
            c.showPage()
            y = height - 40
        c.drawString(40, y, line[:200])
        y -= 12
    c.save()

def edit_pdf(input_pdf: str, output_pdf: str, edit_instructions: str):
    md = pdf_to_markdown(input_pdf)
    prompt = f"Original document:\n\n{md}\n\nEdit instructions:\n{edit_instructions}\n\nReturn the full edited document in Markdown."
    edited_md = ask_llm(prompt)
    markdown_to_pdf(edited_md, output_pdf)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python ai_pdf_editor.py input.pdf output.pdf \"Make these edits...\"")
        sys.exit(1)
    edit_pdf(sys.argv[1], sys.argv[2], sys.argv[3])
