import tkinter as tk
from tkinter import messagebox
from pytube import YouTube
from pydub import AudioSegment
import os
import requests

# Optional: AI title cleaner
def clean_title_with_ai(title):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",  # Replace with your LLM endpoint
            json={"model": "llama3", "prompt": f"Clean this YouTube title for saving as MP3: {title}", "stream": False}
        )
        return response.json()["response"].strip()
    except:
        return title

def download_mp3():
    url = url_entry.get()
    try:
        yt = YouTube(url)
        title = yt.title
        cleaned_title = clean_title_with_ai(title)
        stream = yt.streams.filter(only_audio=True).first()
        out_file = stream.download(filename="temp_audio")
        mp3_file = f"{cleaned_title}.mp3"
        AudioSegment.from_file(out_file).export(mp3_file, format="mp3")
        os.remove(out_file)
        messagebox.showinfo("Success", f"Downloaded: {mp3_file}")
    except Exception as e:
        messagebox.showerror("Error", str(e))

# GUI setup
root = tk.Tk()
root.title("YouTube MP3 Downloader")

tk.Label(root, text="YouTube URL:").pack(pady=5)
url_entry = tk.Entry(root, width=50)
url_entry.pack(pady=5)

tk.Button(root, text="Download MP3", command=download_mp3).pack(pady=10)

root.mainloop()
