#!/usr/bin/env python3
import sys
import socket
import paramiko
import getpass
import threading
import termios
import tty
import select
import os

# --------- CONFIG / EXTENSIBILITY HOOKS ----------
# You can wire these to CLI args, config files, or an LLM front-end.
HOST = None
PORT = 22
USERNAME = None
PASSWORD = None  # If None, will prompt
# -------------------------------------------------


def posix_shell(chan):
    """
    Simple interactive shell for POSIX systems.
    """
    old_tty = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

        while True:
            r, w, e = select.select([chan, sys.stdin], [], [])
            if chan in r:
                try:
                    data = chan.recv(1024)
                except socket.timeout:
                    continue
                if len(data) == 0:
                    break
                sys.stdout.write(data.decode(errors="ignore"))
                sys.stdout.flush()
            if sys.stdin in r:
                x = os.read(sys.stdin.fileno(), 1024)
                if len(x) == 0:
                    break
                chan.send(x)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)


def windows_shell(chan):
    """
    Very basic interactive shell for Windows (no raw mode).
    """
    def write_all(sock):
        while True:
            data = sock.recv(1024)
            if not data:
                break
            sys.stdout.write(data.decode(errors="ignore"))
            sys.stdout.flush()

    writer = threading.Thread(target=write_all, args=(chan,))
    writer.daemon = True
    writer.start()

    try:
        while True:
            d = sys.stdin.read(1)
            if not d:
                break
            chan.send(d)
    except EOFError:
        pass


def main():
    global HOST, USERNAME, PASSWORD, PORT

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} host [port] [username]")
        sys.exit(1)

    HOST = sys.argv[1]
    if len(sys.argv) >= 3:
        PORT = int(sys.argv[2])
    if len(sys.argv) >= 4:
        USERNAME = sys.argv[3]

    if USERNAME is None:
        USERNAME = getpass.getuser()

    PASSWORD = getpass.getpass(f"Password for {USERNAME}@{HOST}: ")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # admin-safe? change to RejectPolicy in prod

    try:
        client.connect(
            HOST,
            port=PORT,
            username=USERNAME,
            password=PASSWORD,
            look_for_keys=False,
            allow_agent=False,
            timeout=10,
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    chan = client.invoke_shell()
    chan.settimeout(0.0)

    print(f"*** Connected to {HOST}. Interactive shell opened. ***")

    try:
        if os.name == "posix":
            posix_shell(chan)
        else:
            windows_shell(chan)
    finally:
        chan.close()
        client.close()
        print("\n*** Session closed. ***")


if __name__ == "__main__":
    main()
