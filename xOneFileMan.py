#!/usr/bin/env python3
import os
import json
import ftplib
import getpass
import pathlib
import textwrap
import requests

# ==========================
# CONFIG / BACKEND CONTRACT
# ==========================
#
# - You provide:
#   * LLM endpoint + API key (OpenAI-compatible style assumed)
#   * FTP server, username, password
#
# - LLM must return a JSON object:
#   {
#     "actions": [
#       {
#         "type": "local_list" | "local_read" | "local_write" |
#                 "ftp_list"   | "ftp_download" | "ftp_upload",
#         "path": "<path or remote path>",
#         "content": "<optional content for write/upload>",
#         "notes": "<optional explanation>"
#       }
#     ]
#   }
#
# - This script:
#   * Sends user query + context to LLM
#   * Parses JSON
#   * Executes actions safely
#   * Prints results

LLM_API_URL = "https://api.openai.com/v1/chat/completions"  # adjust if needed
LLM_MODEL   = "gpt-4.1-mini"                                # adjust if needed
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# ==========================
# LLM CLIENT
# ==========================

def call_llm(system_prompt: str, user_prompt: str) -> str:
    if not LLM_API_KEY:
        raise RuntimeError("Set LLM_API_KEY environment variable first.")

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.1,
    }

    resp = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


SYSTEM_PROMPT = textwrap.dedent("""
You are an AI file manager controller.

You receive a natural language request from the user about:
- local files and directories
- FTP files and directories

You MUST respond ONLY with a valid JSON object of the form:

{
  "actions": [
    {
      "type": "local_list" | "local_read" | "local_write" |
              "ftp_list"   | "ftp_download" | "ftp_upload",
      "path": "<path or remote path>",
      "content": "<optional content for write/upload>",
      "notes": "<optional explanation>"
    }
  ]
}

Rules:
- Use relative paths unless the user clearly wants absolute.
- For listing, use "local_list" or "ftp_list".
- For reading a local file, use "local_read".
- For writing a local file, use "local_write" and include 'content'.
- For downloading from FTP to local, use "ftp_download" with 'path' as remote path.
- For uploading from local to FTP, use "ftp_upload" with 'path' as remote path and 'content' optional (we will read local file if not provided).
- If unsure, choose the safest minimal action.
- Never include explanations outside the JSON. Put any explanation in 'notes'.
""").strip()

# ==========================
# FTP CLIENT WRAPPER
# ==========================

class FTPClient:
    def __init__(self, host: str, user: str, password: str, port: int = 21):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.ftp = None

    def connect(self):
        self.ftp = ftplib.FTP()
        self.ftp.connect(self.host, self.port, timeout=30)
        self.ftp.login(self.user, self.password)

    def close(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                self.ftp.close()
            self.ftp = None

    def list_dir(self, path: str = "."):
        if not self.ftp:
            self.connect()
        items = []
        self.ftp.retrlines(f"LIST {path}", items.append)
        return items

    def download_file(self, remote_path: str, local_path: str):
        if not self.ftp:
            self.connect()
        with open(local_path, "wb") as f:
            self.ftp.retrbinary(f"RETR {remote_path}", f.write)

    def upload_file(self, local_path: str, remote_path: str):
        if not self.ftp:
            self.connect()
        with open(local_path, "rb") as f:
            self.ftp.storbinary(f"STOR {remote_path}", f)


# ==========================
# ACTION EXECUTION
# ==========================

def safe_local_path(path: str) -> pathlib.Path:
    # Simple safety: resolve relative to current working directory
    base = pathlib.Path.cwd()
    p = (base / path).resolve()
    if base not in p.parents and p != base:
        raise PermissionError(f"Refusing to access path outside working dir: {p}")
    return p

def execute_action(action: dict, ftp_client: FTPClient):
    atype = action.get("type")
    path  = action.get("path", "")
    content = action.get("content", None)
    notes = action.get("notes", "")

    print(f"\n[Action] {atype} | path={path}")
    if notes:
        print(f"[Notes] {notes}")

    if atype == "local_list":
        p = safe_local_path(path or ".")
        if not p.exists():
            print(f"  ! Path does not exist: {p}")
            return
        if p.is_dir():
            for item in p.iterdir():
                print("  ", item.name, "/" if item.is_dir() else "")
        else:
            print(f"  ! Not a directory: {p}")

    elif atype == "local_read":
        p = safe_local_path(path)
        if not p.exists() or not p.is_file():
            print(f"  ! File not found: {p}")
            return
        print(f"--- {p} ---")
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            print(f.read())
        print("-----------")

    elif atype == "local_write":
        p = safe_local_path(path)
        parent = p.parent
        parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content or "")
        print(f"  + Wrote file: {p}")

    elif atype == "ftp_list":
        items = ftp_client.list_dir(path or ".")
        for line in items:
            print("  ", line)

    elif atype == "ftp_download":
        # remote path -> local file with same name in cwd
        remote = path
        local = safe_local_path(os.path.basename(remote))
        ftp_client.download_file(remote, str(local))
        print(f"  + Downloaded {remote} -> {local}")

    elif atype == "ftp_upload":
        # local file must exist; remote path is given
        remote = path
        # If content is provided, write to temp local file first
        if content is not None:
            tmp = safe_local_path(f"tmp_upload_{os.path.basename(remote)}")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            local = tmp
        else:
            # assume remote filename matches local filename
            local = safe_local_path(os.path.basename(remote))

        if not local.exists():
            print(f"  ! Local file not found for upload: {local}")
            return

        ftp_client.upload_file(str(local), remote)
        print(f"  + Uploaded {local} -> {remote}")

    else:
        print(f"  ! Unknown action type: {atype}")


def execute_plan(plan_json: str, ftp_client: FTPClient):
    try:
        data = json.loads(plan_json)
    except json.JSONDecodeError as e:
        print("LLM returned invalid JSON:")
        print(plan_json)
        print("Error:", e)
        return

    actions = data.get("actions", [])
    if not isinstance(actions, list):
        print("Invalid plan: 'actions' is not a list.")
        return

    for action in actions:
        if not isinstance(action, dict):
            print("Invalid action (not an object):", action)
            continue
        execute_action(action, ftp_client)


# ==========================
# MAIN LOOP
# ==========================

def main():
    print("=== LLM File Manager with FTP ===")
    print("Natural language commands for local and FTP files.")
    print("Type 'exit' or 'quit' to leave.\n")

    ftp_host = input("FTP host (empty to skip FTP): ").strip()
    ftp_user = ""
    ftp_pass = ""
    ftp_client = None

    if ftp_host:
        ftp_user = input("FTP user: ").strip()
        ftp_pass = getpass.getpass("FTP password: ")
        ftp_client = FTPClient(ftp_host, ftp_user, ftp_pass)

    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit"):
            break

        user_prompt = f"User request: {query}\nCurrent working directory: {os.getcwd()}"
        if ftp_host:
            user_prompt += f"\nFTP host: {ftp_host}"

        try:
            plan = call_llm(SYSTEM_PROMPT, user_prompt)
            print("\n[LLM RAW RESPONSE]")
            print(plan)
            execute_plan(plan, ftp_client if ftp_client else FTPClient("localhost", "", ""))
        except Exception as e:
            print("Error:", e)

    if ftp_client:
        ftp_client.close()
    print("Bye.")

if __name__ == "__main__":
    main()
