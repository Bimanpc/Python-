import tkinter as tk
import requests

root = tk.Tk()
root.title("Web Client")

def fetch_data():
    url = "http://localhost:5000"
    response = requests.get(url)
    message.set(response.text)

message = tk.StringVar()
message.set("Waiting...")
label = tk.Label(root, textvariable=message)
label.pack()

button = tk.Button(root, text="Fetch from Local Server", command=fetch_data)
button.pack()

root.mainloop()
