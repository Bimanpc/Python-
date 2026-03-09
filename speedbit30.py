#!/usr/bin/env python3
"""
AI WiFi Speed Test

What this script does:
- Runs a Speedtest.net test (download/upload/ping) using the speedtest-cli library.
- Gathers basic Wi-Fi info (SSID and signal strength / RSSI) on Windows/macOS/Linux when available.
- Appends each test result to a CSV log.
- When enough historical data exists, trains:
    - a RandomForestRegressor to predict expected download speed from features (RSSI, hour, day_of_week)
    - an IsolationForest to detect anomalous speed test runs
- Prints the immediate test, the AI prediction, and whether the run looks anomalous.

Requirements:
pip install speedtest-cli pandas scikit-learn

Usage:
    python ai_wifi_speed_test.py                  # run one test, log, and (if enough data) show AI analysis
    python ai_wifi_speed_test.py --csv path.csv   # use custom CSV path
    python ai_wifi_speed_test.py --no-log         # run test but don't append to CSV
"""
from __future__ import annotations
import argparse
import csv
import datetime
import os
import platform
import re
import subprocess
import sys
from typing import Optional, Tuple

# Optional imports; we'll provide user-friendly error messages if missing.
try:
    import speedtest
except Exception as e:
    print("Missing dependency: speedtest (install with `pip install speedtest-cli`)")
    raise

try:
    import pandas as pd
except Exception as e:
    print("Missing dependency: pandas (install with `pip install pandas`)")
    raise

try:
    from sklearn.ensemble import RandomForestRegressor, IsolationForest
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error
except Exception as e:
    print("Missing dependency: scikit-learn (install with `pip install scikit-learn`)")
    raise

CSV_COLUMNS = ["timestamp", "ssid", "rssi", "download_mbps", "upload_mbps", "ping_ms", "notes"]


def get_wifi_info() -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Attempt to return (ssid, rssi_dbm_or_percent, notes) for the current wifi.
    rssi: On some platforms returned as percent (0-100) or dBm (negative). We'll normalize later.
    """
    system = platform.system().lower()
    try:
        if system == "windows":
            return _get_wifi_info_windows()
        elif system == "darwin":
            return _get_wifi_info_macos()
        elif system == "linux":
            return _get_wifi_info_linux()
        else:
            return None, None, f"unsupported-platform-{system}"
    except Exception as e:
        return None, None, f"error-getting-wifi:{e}"


def _get_wifi_info_windows() -> Tuple[Optional[str], Optional[float], str]:
    # Uses `netsh wlan show interfaces`
    try:
        out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], text=True, stderr=subprocess.DEVNULL)
        ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", out, flags=re.MULTILINE)
        signal_match = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, flags=re.MULTILINE)
        ssid = ssid_match.group(1).strip() if ssid_match else None
        rssi_percent = float(signal_match.group(1)) if signal_match else None
        return ssid, rssi_percent, "windows-netsh-signal-percent"
    except Exception as e:
        return None, None, f"windows-error:{e}"


def _get_wifi_info_macos() -> Tuple[Optional[str], Optional[float], str]:
    # Uses the airport utility which lives in a private framework path
    airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    try:
        out = subprocess.check_output([airport_path, "-I"], text=True, stderr=subprocess.DEVNULL)
        ssid_match = re.search(r"^\s*SSID:\s*(.+)$", out, flags=re.MULTILINE)
        rssi_match = re.search(r"^\s*agrCtlRSSI:\s*(-?\d+)", out, flags=re.MULTILINE)
        ssid = ssid_match.group(1).strip() if ssid_match else None
        rssi_dbm = float(rssi_match.group(1)) if rssi_match else None
        return ssid, rssi_dbm, "macos-airport-dbm"
    except Exception as e:
        return None, None, f"macos-error:{e}"


def _get_wifi_info_linux() -> Tuple[Optional[str], Optional[float], str]:
    # Try nmcli, then iwconfig fallback
    try:
        out = subprocess.check_output(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], text=True, stderr=subprocess.DEVNULL)
        # lines like: "yes:MySSID:60"
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "yes":
                ssid = parts[1] if parts[1] != "--" else None
                signal = float(parts[2]) if parts[2] else None
                return ssid, signal, "linux-nmcli-signal-percent"
    except Exception:
        # fallback to iwconfig
        try:
            out = subprocess.check_output(["iwconfig"], text=True, stderr=subprocess.DEVNULL)
            # find ESSID and Signal level
            ssid_match = re.search(r'ESSID:"([^"]+)"', out)
            signal_match = re.search(r"Signal level=(\-?\d+) dBm", out)
            ssid = ssid_match.group(1) if ssid_match else None
            rssi_dbm = float(signal_match.group(1)) if signal_match else None
            return ssid, rssi_dbm, "linux-iwconfig-dbm"
        except Exception as e:
            return None, None, f"linux-error:{e}"
    return None, None, "no-wifi-found"


def run_speedtest(timeout: int = 30) -> Tuple[float, float, float]:
    """
    Run a speedtest and return (download_mbps, upload_mbps, ping_ms)
    """
    s = speedtest.Speedtest()
    s.get_best_server()
    s.download(threads=1)   # threads=1 to be conservative
    s.upload(threads=1, pre_allocate=False)
    res = s.results.dict()
    # download and upload are in bits per second
    download_mbps = res.get("download", 0) / 1e6
    upload_mbps = res.get("upload", 0) / 1e6
    ping_ms = res.get("ping", 0)
    return download_mbps, upload_mbps, ping_ms


def append_to_csv(path: str, row: dict, create_if_missing: bool = True) -> None:
    exists = os.path.exists(path)
    if not exists and not create_if_missing:
        raise FileNotFoundError(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def load_history(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    # Ensure columns exist
    df = df.copy()
    # normalize rssi: if percent (0-100) keep, if negative (<0) convert to approximate percent
    def normalize_rssi(x):
        try:
            if pd.isna(x):
                return None
            v = float(x)
            if v < -10:  # likely dBm
                # convert dBm (-100..-30) to percent 0..100 (rough)
                # clamp
                dbm = max(min(v, -30.0), -100.0)
                pct = (dbm + 100.0) / 70.0 * 100.0
                return pct
            else:
                # likely already percent
                return max(0.0, min(100.0, v))
        except Exception:
            return None

    df["rssi_pct"] = df["rssi"].apply(normalize_rssi)
    df["hour"] = df["timestamp"].dt.hour
    df["dow"] = df["timestamp"].dt.dayofweek
    # Fill missing rssi with median
    if df["rssi_pct"].notna().any():
        median_rssi = df["rssi_pct"].median()
    else:
        median_rssi = 50.0
    df["rssi_pct"] = df["rssi_pct"].fillna(median_rssi)
    X = df[["rssi_pct", "hour", "dow"]]
    y = df["download_mbps"]
    return X, y


def train_models(df: pd.DataFrame):
    X, y = prepare_features(df)
    # regression
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    reg = RandomForestRegressor(n_estimators=100, random_state=42)
    reg.fit(X_train, y_train)
    y_pred = reg.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    # anomaly detector on residuals or raw download speed
    iso = IsolationForest(contamination=0.05, random_state=42)
    iso.fit(X)  # or use download values as well; we'll use X to detect odd combinations
    return reg, iso, mae


def analyze_with_ai(reg, iso, row_df: pd.DataFrame):
    X_new, _ = prepare_features(row_df)
    pred = float(reg.predict(X_new)[0])
    iso_score = iso.score_samples(X_new)[0]  # higher is more normal
    iso_pred = iso.predict(X_new)[0]  # 1 = normal, -1 = anomaly
    return pred, iso_score, iso_pred


def main():
    parser = argparse.ArgumentParser(description="AI WiFi Speed Test")
    parser.add_argument("--csv", "-c", default="wifi_speed_log.csv", help="CSV file to append/read history")
    parser.add_argument("--no-log", action="store_true", help="Don't append current test to CSV")
    parser.add_argument("--min-history", type=int, default=30, help="Minimum rows required to train AI models")
    args = parser.parse_args()

    print("Gathering Wi-Fi info...")
    ssid, rssi, notes = get_wifi_info()

    print("Running speedtest (this may take 20-40s)...")
    try:
        download_mbps, upload_mbps, ping_ms = run_speedtest()
    except Exception as e:
        print("Speedtest failed:", e)
        sys.exit(1)

    ts = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    row = {
        "timestamp": ts.isoformat(),
        "ssid": ssid or "",
        "rssi": rssi if rssi is not None else "",
        "download_mbps": round(download_mbps, 3),
        "upload_mbps": round(upload_mbps, 3),
        "ping_ms": round(ping_ms, 3),
        "notes": notes or "",
    }

    print("\nResult:")
    print(f"  Time (UTC): {row['timestamp']}")
    print(f"  SSID: {row['ssid'] or '(unknown)'}")
    print(f"  RSSI: {row['rssi'] if row['rssi'] != '' else '(unknown)'}  ({row['notes']})")
    print(f"  Download: {row['download_mbps']} Mbps")
    print(f"  Upload:   {row['upload_mbps']} Mbps")
    print(f"  Ping:     {row['ping_ms']} ms")

    # Append to CSV
    if not args.no_log:
        try:
            append_to_csv(args.csv, row)
            print(f"\nLogged to {args.csv}")
        except Exception as e:
            print("Failed to append to CSV:", e)

    # Load history and train AI if enough rows
    df = load_history(args.csv)
    if df is None or len(df) < args.min_history:
        if df is None:
            print(f"\nNo history available at {args.csv}. AI analysis requires at least {args.min_history} rows.")
        else:
            print(f"\nOnly {len(df)} history rows found. AI analysis requires at least {args.min_history} rows.")
        return

    print("\nTraining AI models on historical data (this may take a few seconds)...")
    try:
        reg, iso, mae = train_models(df)
    except Exception as e:
        print("Model training failed:", e)
        return

    # Analyze current row with AI
    row_df = pd.DataFrame([{
        "timestamp": pd.to_datetime(row["timestamp"]),
        "rssi": row["rssi"],
        "download_mbps": row["download_mbps"]
    }])
    pred, iso_score, iso_pred = analyze_with_ai(reg, iso, row_df)
    print("\nAI Analysis:")
    print(f"  Predicted expected download speed: {pred:.2f} Mbps (trained MAE ~ {mae:.2f} Mbps)")
    print(f"  Actual download speed: {row['download_mbps']:.2f} Mbps")
    if iso_pred == -1:
        print(f"  Anomaly detector: FLAGGED as anomaly (score={iso_score:.3f})")
    else:
        print(f"  Anomaly detector: normal (score={iso_score:.3f})")

    # Simple recommendation
    delta = row["download_mbps"] - pred
    if delta < - (max(5.0, mae * 1.5)):
        print("\nRecommendation: Download speed is significantly below expected. Try:")
        print("  - Move closer to the AP or reduce interference.")
        print("  - Reboot the router.")
        print("  - Run multiple tests at different times to confirm.")
    elif delta < -1.0:
        print("\nNote: Slightly below expected. Consider retesting or checking interference.")
    else:
        print("\nStatus: Download speed is at or above expected for current conditions.")

    print("\nDone.")


if __name__ == "__main__":
    main()
