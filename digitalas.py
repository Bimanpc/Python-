import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import platform
import json
import threading
import re

try:
    import requests  # For LLM API calls
except ImportError:
    requests = None

class WIFISignalMeterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("WiFi Signal Meter with AI Analysis")
        self.root.geometry("700x500")
        
        self.os_type = platform.system()
        self.llm_api_key = None
        self.llm_endpoint = None
        
        self.setup_ui()
        self.start_auto_refresh()
    
    def setup_ui(self):
        # Title
        title_frame = ttk.Frame(self.root)
        title_frame.pack(pady=10)
        
        title_label = tk.Label(title_frame, text="📡 WiFi Signal Meter", 
                              font=("Arial", 18, "bold"))
        title_label.pack()
        
        # Status Label
        self.status_label = tk.Label(self.root, text="Scanning...", 
                                    fg="orange", font=("Arial", 10))
        self.status_label.pack()
        
        # WiFi List Frame
        list_frame = ttk.LabelFrame(self.root, text="Available Networks", 
                                   padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Create Treeview for WiFi networks
        columns = ("SSID", "Signal", "Security", "Channel")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
        
        self.tree.heading("SSID", text="Network Name")
        self.tree.heading("Signal", text="Signal Strength (dBm)")
        self.tree.heading("Security", text="Security")
        self.tree.heading("Channel", text="Channel")
        
        self.tree.column("SSID", width=200)
        self.tree.column("Signal", width=100)
        self.tree.column("Security", width=100)
        self.tree.column("Channel", width=60)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, 
                                  command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Control Buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.scan_btn = ttk.Button(button_frame, text="Scan Now", 
                                   command=self.scan_wifi)
        self.scan_btn.grid(row=0, column=0, padx=5)
        
        self.ai_analyze_btn = ttk.Button(button_frame, text="AI Analyze Best Network", 
                                         command=self.ai_analyze_networks)
        self.ai_analyze_btn.grid(row=0, column=1, padx=5)
        
        self.settings_btn = ttk.Button(button_frame, text="LLM Settings", 
                                       command=self.open_llm_settings)
        self.settings_btn.grid(row=0, column=2, padx=5)
        
        # Analysis Output
        analysis_frame = ttk.LabelFrame(self.root, text="AI Recommendations", 
                                       padding=10)
        analysis_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.analysis_text = tk.Text(analysis_frame, height=5, font=("Arial", 9))
        self.analysis_text.pack(fill=tk.X)
    
    def scan_wifi_windows(self):
        """Scan WiFi on Windows"""
        try:
            result = subprocess.run(['netsh', 'wlan', 'show', 'network'], 
                                   capture_output=True, text=True)
            networks = []
            
            ssid_pattern = r'SSID\s+\d+\s*:\s*(.+)'
            signal_pattern = r'Signal\s*:\s*(\d+)%'
            security_pattern = r'Security\s*:\s*(.+)'
            
            matches = re.findall(ssid_pattern, result.stdout)
            signals = re.findall(signal_pattern, result.stdout)
            securities = re.findall(security_pattern, result.stdout)
            
            for i, ssid in enumerate(matches[:len(signals)]):
                signal_dbm = -100 + int(signals[i]) if i < len(signals) else -100
                sec = securities[i] if i < len(securities) else "Unknown"
                networks.append({
                    "ssid": ssid.strip(),
                    "signal": signal_dbm,
                    "security": sec
                })
            
            return networks
        except Exception as e:
            messagebox.showerror("Error", f"Windows scan failed: {str(e)}")
            return []
    
    def scan_wifi_linux(self):
        """Scan WiFi on Linux"""
        try:
            result = subprocess.run(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 
                                    'dev', 'wifi'], capture_output=True, text=True)
            networks = []
            
            for line in result.stdout.strip().split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    ssid = parts[0].strip()
                    signal = -100 + int(parts[1]) if parts[1].isdigit() else -100
                    security = parts[2].strip() if len(parts[2]) > 0 else "Open"
                    
                    if ssid and ssid != '--':
                        networks.append({
                            "ssid": ssid,
                            "signal": signal,
                            "security": security
                        })
            
            return networks
        except Exception as e:
            messagebox.showerror("Error", f"Linux scan failed: {str(e)}")
            return []
    
    def scan_wifi_macos(self):
        """Scan WiFi on macOS"""
        try:
            airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
            result = subprocess.run([airport_path, '-s'], capture_output=True, text=True)
            networks = []
            
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                parts = line.split()
                if len(parts) >= 3:
                    ssid = " ".join(parts[:-3])
                    signal = int(parts[-3])
                    security = parts[-1] if len(parts) > 3 else "Unknown"
                    
                    networks.append({
                        "ssid": ssid,
                        "signal": signal,
                        "security": security
                    })
            
            return networks
        except Exception as e:
            messagebox.showerror("Error", f"macOS scan failed: {str(e)}")
            return []
    
    def scan_wifi(self):
        """Scan WiFi based on OS"""
        self.status_label.config(text="Scanning...", fg="orange")
        
        def do_scan():
            if self.os_type == "Windows":
                networks = self.scan_wifi_windows()
            elif self.os_type == "Linux":
                networks = self.scan_wifi_linux()
            elif self.os_type == "Darwin":
                networks = self.scan_wifi_macos()
            else:
                networks = []
            
            self.root.after(0, lambda: self.update_wifi_list(networks))
            self.root.after(0, lambda: self.status_label.config(
                text=f"Found {len(networks)} networks", fg="green"))
        
        thread = threading.Thread(target=do_scan)
        thread.daemon = True
        thread.start()
    
    def update_wifi_list(self, networks):
        """Update the Treeview with scanned networks"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        for net in sorted(networks, key=lambda x: x["signal"], reverse=True):
            signal_strength = net["signal"]
            
            # Color code signal strength
            if signal_strength >= -50:
                color = "#00AA00"  # Excellent
            elif signal_strength >= -70:
                color = "#FFFF00"  # Good
            elif signal_strength >= -85:
                color = "#FF8800"  # Fair
            else:
                color = "#FF0000"  # Poor
            
            self.tree.insert("", tk.END, values=(
                net["ssid"],
                str(net["signal"]),
                net["security"],
                "-"
            ), tags=(color,))
        
        self.tree.tag_configure("#00AA00", foreground="#00AA00")
        self.tree.tag_configure("#FFFF00", foreground="#FFFF00")
        self.tree.tag_configure("#FF8800", foreground="#FF8800")
        self.tree.tag_configure("#FF0000", foreground="#FF0000")
    
    def ai_analyze_networks(self):
        """Send WiFi data to LLM for analysis"""
        networks = []
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            networks.append({
                "ssid": values[0],
                "signal": int(values[1]),
                "security": values[2]
            })
        
        if not networks:
            messagebox.showinfo("Info", "No networks to analyze. Scan first!")
            return
        
        if not self.llm_api_key:
            messagebox.showwarning("Warning", 
                "LLM API key not configured! Click 'LLM Settings' to add it.")
            # Show local analysis instead
            self.local_analysis(networks)
            return
        
        if requests is None:
            messagebox.showerror("Error", "requests library not installed!")
            return
        
        def send_to_llm():
            prompt = f"""Analyze these WiFi networks and recommend the best one:

{json.dumps(networks, indent=2)}

Consider: Signal strength, security type, and potential interference.
Give a brief recommendation."""
            
            try:
                response = requests.post(
                    self.llm_endpoint,
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                    json={"model": "gpt-4", "messages": [{"role": "user", "content": prompt}]},
                    timeout=10
                )
                
                result = response.json()
                analysis = result.get('choices', [{}])[0].get('message', {}).get('content', 'No analysis received')
                
                self.root.after(0, lambda: self.update_analysis(analysis))
            except Exception as e:
                self.root.after(0, lambda: self.update_analysis(f"Error: {str(e)}"))
        
        thread = threading.Thread(target=send_to_llm)
        thread.daemon = True
        thread.start()
    
    def local_analysis(self, networks):
        """Basic local analysis without LLM"""
        if not networks:
            return
        
        best = max(networks, key=lambda x: x["signal"])
        recommendation = f"RECOMMENDATION (Local Analysis):\n\n"
        recommendation += f"Best Network: {best['ssid']}\n"
        recommendation += f"Signal: {best['signal']} dBm\n"
        recommendation += f"Security: {best['security']}\n\n"
        
        strong_signals = [n for n in networks if n["signal"] >= -65]
        recommendation += f"Strong Networks (>={-65} dBm): {len(strong_signals)}\n"
        recommendation += f"Total Scanned: {len(networks)}"
        
        self.update_analysis(recommendation)
    
    def update_analysis(self, text):
        """Update analysis text box"""
        self.analysis_text.delete(1.0, tk.END)
        self.analysis_text.insert(tk.END, text)
    
    def open_llm_settings(self):
        """Open LLM configuration dialog"""
        settings_win = tk.Toplevel(self.root)
        settings_win.title("LLM Settings")
        settings_win.geometry("400x250")
        
        ttk.Label(settings_win, text="API Endpoint:", font=("Arial", 10)).pack(pady=5)
        endpoint_entry = ttk.Entry(settings_win, width=50)
        endpoint_entry.insert(0, "https://api.openai.com/v1/chat/completions")
        endpoint_entry.pack(pady=2)
        
        ttk.Label(settings_win, text="API Key:", font=("Arial", 10)).pack(pady=5)
        api_key_entry = ttk.Entry(settings_win, width=50, show="*")
        api_key_entry.pack(pady=2)
        
        def save_settings():
            self.llm_endpoint = endpoint_entry.get()
            self.llm_api_key = api_key_entry.get()
            settings_win.destroy()
            messagebox.showinfo("Success", "Settings saved!")
        
        ttk.Button(settings_win, text="Save", command=save_settings).pack(pady=15)
    
    def start_auto_refresh(self):
        """Auto-refresh scan every 30 seconds"""
        self.scan_wifi()
        self.root.after(30000, self.start_auto_refresh)


if __name__ == "__main__":
    root = tk.Tk()
    app = WIFISignalMeterApp(root)
    root.mainloop()
