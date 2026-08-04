#!/usr/bin/env python3
"""RAM Meter - Displays real-time RAM usage on Linux Mint"""

import subprocess
import time
import sys


def get_ram_info():
    """Parse /proc/meminfo for RAM statistics."""
    info = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = int(parts[1].split()[0])  # value in kB
                    info[key] = val
    except FileNotFoundError:
        print("Error: /proc/meminfo not found. This script requires Linux.")
        sys.exit(1)
    return info


def get_top_ram_processes(n=10):
    """Return top N processes by RAM usage using ps."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,rss,comm", "--sort=-rss"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().split("\n")[1:n + 1]
        procs = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                pid = parts[0]
                rss_kb = int(parts[1])
                name = " ".join(parts[2:])
                procs.append((pid, rss_kb, name))
        return procs
    except Exception as e:
        print(f"Could not retrieve process list: {e}")
        return []


def format_size(kb):
    """Convert kB to human-readable string."""
    mb = kb / 1024
    gb = mb / 1024
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{mb:.1f} MB"


def print_bar(percent, width=40):
    """Render a text progress bar."""
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"


def main():
    while True:
        mem = get_ram_info()

        total_kb     = mem.get("MemTotal", 0)
        available_kb = mem.get("MemAvailable", 0)
        free_kb      = mem.get("MemFree", 0)
        buffers_kb   = mem.get("Buffers", 0)
        cached_kb    = mem.get("Cached", 0)
        swap_total   = mem.get("SwapTotal", 0)
        swap_free    = mem.get("SwapFree", 0)

        used_kb = total_kb - available_kb
        percent = (used_kb / total_kb * 100) if total_kb else 0
        swap_used_kb = swap_total - swap_free
        swap_pct = (swap_used_kb / swap_total * 100) if swap_total else 0

        # Clear screen
        print("\033[2J\033[H", end="")

        print("=" * 52)
        print("         🧠  LINUX MINT RAM METER")
        print("=" * 52)

        # --- RAM ---
        print(f"\n  Total RAM:      {format_size(total_kb):>12}")
        print(f"  Used RAM:       {format_size(used_kb):>12}  "
              f"{print_bar(percent)}  {percent:.1f}%")
        print(f"  Available RAM:  {format_size(available_kb):>12}")
        print(f"  Free RAM:       {format_size(free_kb):>12}")
        print(f"  Buffers:        {format_size(buffers_kb):>12}")
        print(f"  Cached:         {format_size(cached_kb):>12}")

        # --- Swap ---
        if swap_total > 0:
            print(f"\n  Swap Total:     {format_size(swap_total):>12}")
            print(f"  Swap Used:      {format_size(swap_used_kb):>12}  "
                  f"{print_bar(swap_pct)}  {swap_pct:.1f}%")
        else:
            print("\n  Swap:           Disabled")

        # --- Top Processes ---
        print(f"\n  {'─' * 48}")
        print(f"  Top RAM-consuming processes:")
        print(f"  {'PID':>7}  {'RSS':>10}  {'Process'}")
        print(f"  {'─' * 48}")
        for pid, rss, name in get_top_ram_processes(8):
            print(f"  {pid:>7}  {format_size(rss):>10}  {name}")

        print(f"\n  {'─' * 48}")
        print("  Press Ctrl+C to exit.")

        try:
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n\n  Goodbye! 👋\n")
            break


if __name__ == "__main__":
    main()
