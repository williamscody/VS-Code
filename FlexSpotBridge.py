"""
FlexRadio + SDC Cluster + MacLoggerDX Spot Bridge
-------------------------------------------------

This script connects to:

1. A FlexRadio TCP control port (4992)
2. A local SDC DX cluster (port 7373)

It stores incoming cluster spots and when you tune
the Flex slice near a spotted frequency it:

• prints the matched callsign
• sends the callsign to MacLoggerDX
• optionally sets the radio mode

Tested environment:
Flex 8400
SmartSDR
SDC cluster
MacLoggerDX
Python 3.14
"""

import socket
import subprocess
import time
import re
import threading
import tkinter as tk
import sys
import json
import os
current_freq = None

# ------------------------------------------------
# USER SETTINGS
# ------------------------------------------------

# Flex radio IP
FLEX_IP = "192.168.68.157"

# Flex API port
FLEX_PORT = 4992

# Local SDC cluster
CLUSTER_HOST = "localhost"
CLUSTER_PORT = 7373

# Your callsign (cluster login)
CALLSIGN = "K3CDY"

# Spot validity time
SPOT_TIMEOUT = 600

# Frequency tolerance for match (Hz)
FREQ_MATCH_HZ = 1000

# Minimum frequency change to trigger spot detection (Hz)
FREQ_CHANGE_HZ = 500

# Storage for cluster spots
spots = []

# ------------------------------------------------
# SETTINGS PERSISTENCE
# ------------------------------------------------

SETTINGS_FILE = os.path.expanduser("~/Library/Preferences/FlexSpotBridge.json")

def load_settings():
    global FLEX_IP, FLEX_PORT, CLUSTER_HOST, CLUSTER_PORT, CALLSIGN, SPOT_TIMEOUT, FREQ_MATCH_HZ, FREQ_CHANGE_HZ
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            FLEX_IP = data.get("FLEX_IP", FLEX_IP)
            FLEX_PORT = int(data.get("FLEX_PORT", FLEX_PORT))
            CLUSTER_HOST = data.get("CLUSTER_HOST", CLUSTER_HOST)
            CLUSTER_PORT = int(data.get("CLUSTER_PORT", CLUSTER_PORT))
            CALLSIGN = data.get("CALLSIGN", CALLSIGN)
            SPOT_TIMEOUT = int(data.get("SPOT_TIMEOUT", SPOT_TIMEOUT))
            FREQ_MATCH_HZ = int(data.get("FREQ_MATCH_HZ", FREQ_MATCH_HZ))
            FREQ_CHANGE_HZ = int(data.get("FREQ_CHANGE_HZ", FREQ_CHANGE_HZ))
        except Exception as e:
            print(f"Failed to load settings: {e}")

def save_settings():
    try:
        data = {
            "FLEX_IP": FLEX_IP,
            "FLEX_PORT": FLEX_PORT,
            "CLUSTER_HOST": CLUSTER_HOST,
            "CLUSTER_PORT": CLUSTER_PORT,
            "CALLSIGN": CALLSIGN,
            "SPOT_TIMEOUT": SPOT_TIMEOUT,
            "FREQ_MATCH_HZ": FREQ_MATCH_HZ,
            "FREQ_CHANGE_HZ": FREQ_CHANGE_HZ,
        }
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save settings: {e}")

load_settings()

class TextRedirector:
    def __init__(self, widget):
        self.widget = widget

    def write(self, str):
        self.widget.insert(tk.END, str)
        self.widget.see(tk.END)

    def flush(self):
        pass


# ------------------------------------------------
# SEND CALLSIGN TO MACLOGGERDX
# ------------------------------------------------

def set_mldx_call(call):

    print(f"Sending to MLDX: {call}")
    
    # Get the currently focused app before opening MLDX
    try:
        result = subprocess.run(
            ["osascript", "-e", "tell application \"System Events\" to name of first application process whose frontmost is true"],
            capture_output=True,
            text=True,
            check=True
        )
        previous_app = result.stdout.strip()
    except subprocess.CalledProcessError:
        previous_app = None
    
    try:
        subprocess.run(["open", f"mldx://lookup?call={call}"], check=True)
        print("MLDX lookup URL opened successfully")
        
        # Give MLDX a moment to come to focus
        time.sleep(0.5)
        
        # Restore focus to the previously focused app
        if previous_app:
            try:
                subprocess.run(
                    ["osascript", "-e", f"tell application \"{previous_app}\" to activate"],
                    check=True
                )
                print(f"Focus restored to {previous_app}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to restore focus to {previous_app}: {e}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to open MLDX lookup URL: {e}")


# ------------------------------------------------
# FLEX MODE CONTROL
# ------------------------------------------------

def set_mode(sock, slice_id, mode):

    cmd = f"C slice set {slice_id} mode={mode}\n"
    sock.send(cmd.encode())


# ------------------------------------------------
# SIMPLE MODE DETECTION (example bands)
# ------------------------------------------------

def auto_mode(sock, slice_id, freq):

    mhz = freq / 1e6

    if 14.070 < mhz < 14.080:
        set_mode(sock, slice_id, "DIGU")

    elif 14.000 < mhz < 14.060:
        set_mode(sock, slice_id, "CW")

    elif 14.150 < mhz < 14.350:
        set_mode(sock, slice_id, "USB")


# ------------------------------------------------
# FIND MATCHING SPOT
# ------------------------------------------------

def find_spot(freq):

    now = time.time()
    print(f"Checking {len(spots)} spots for freq {freq}")

    for spot in spots:

        if now - spot["time"] > SPOT_TIMEOUT:
            continue

        # DEBUG LINE (add this)
        print("Checking spot:", spot["call"], spot["freq"],
              "diff:", abs(spot["freq"] - freq))

        if abs(spot["freq"] - freq) <= FREQ_MATCH_HZ:
            return spot["call"]

    return None

# ------------------------------------------------
# CLUSTER LISTENER
# ------------------------------------------------

def cluster_listener():

    print("Connecting to DX cluster...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((CLUSTER_HOST, CLUSTER_PORT))

    print("DX cluster connected")

    # send callsign login
    sock.sendall((CALLSIGN + "\n").encode())

    buffer = ""

    while True:

        data = sock.recv(4096).decode(errors="ignore")

        if not data:
            continue

        buffer += data

        while "\n" in buffer:

            line, buffer = buffer.split("\n", 1)

            line = line.strip()

            print("Cluster:", line)

            m = re.search(
                r"DX de\s+\S+:\s+(\d+(?:\.\d+)?)\s+([A-Z0-9/]+)",
                line,
                re.IGNORECASE
            )

            if m:

                freq_str = m.group(1)
                freq_float = float(freq_str)
                if freq_float < 100:
                    freq = freq_float * 1e6  # MHz
                else:
                    freq = freq_float * 1000  # kHz
                call = m.group(2)

                spots.append({
                    "freq": freq,
                    "call": call,
                    "time": time.time()
                })

                print("Spot stored:", call, freq)

                # check if radio already tuned to this spot
                global current_freq

                if current_freq is not None:

                    diff = abs(current_freq - freq)

                    print("Checking current freq:", current_freq,
                          "spot:", freq, "diff:", diff)

                    if diff <= FREQ_MATCH_HZ:

                        print("Matched spot:", call)

                        set_mldx_call(call)
# ------------------------------------------------
# FLEX RADIO LISTENER
# ------------------------------------------------

def flex_listener():

    print("Connecting to Flex radio...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLEX_IP, FLEX_PORT))

    print("Flex connected")

    # subscribe to slice updates
    sock.sendall(b"C1|sub slice all\n")

    last_checked_freq = 0
    
    while True:

        data = sock.recv(4096).decode(errors="ignore")
        
        print("Flex data:", data.strip())

        if not data:
            continue

        m = re.search(r"S[^|]+\|slice\s+(\d+).*RF_frequency=(\d+\.\d+)", data)
        
        if m:
        
            slice_id = m.group(1)
            
            freq = float(m.group(2)) * 1e6
            global current_freq
            current_freq = freq   
                 
            print("Current frequency:", freq)
            
            # Only check for spots if frequency change exceeds threshold
            freq_change = abs(freq - last_checked_freq)
            
            if freq_change >= FREQ_CHANGE_HZ:
                print(f"Frequency change: {freq_change} Hz (threshold: {FREQ_CHANGE_HZ} Hz)")
                
                call = find_spot(freq)
                
                if call:
                    print("Matched spot:", call)
                
                    set_mldx_call(call)
                
                    auto_mode(sock, slice_id, freq)
                
                last_checked_freq = freq
            else:
                print(f"Frequency change: {freq_change} Hz - below threshold ({FREQ_CHANGE_HZ} Hz), skipping spot check")
            
# ------------------------------------------------
# MAIN
# ------------------------------------------------

def main():

    cluster_thread = threading.Thread(
        target=cluster_listener,
        daemon=True
    )

    flex_thread = threading.Thread(
        target=flex_listener,
        daemon=True
    )

    cluster_thread.start()
    flex_thread.start()

class TextRedirector:
    def __init__(self, widget):
        self.widget = widget

    def write(self, str):
        self.widget.insert(tk.END, str)
        self.widget.see(tk.END)

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("FlexSpotBridge")
        self.root.geometry("600x400")

        self.text = tk.Text(root, wrap=tk.WORD)
        self.text.pack(expand=True, fill=tk.BOTH)

        # Redirect stdout
        sys.stdout = TextRedirector(self.text)

        # Menu
        menubar = tk.Menu(root)

        # App menu (standard macOS layout: Preferences + Quit)
        appmenu = tk.Menu(menubar, name='apple')


        def clear_spots():
            # Send 'spot clear' to Flex API
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((FLEX_IP, FLEX_PORT))
                sock.sendall(b"C1|spot clear\n")
                sock.close()
                print("All spots cleared on Flex panadapter.")
            except Exception as e:
                print(f"Failed to clear spots on Flex: {e}")


        appmenu.add_command(label="Preferences...", accelerator="⌘,", command=self.open_settings)
        appmenu.add_command(label="Clear All Spots", accelerator="Command-L", command=clear_spots)
        appmenu.add_separator()
        appmenu.add_command(label="Quit", command=root.quit)
        menubar.add_cascade(menu=appmenu)

        # Keyboard shortcut for Clear All Spots (Cmd-L)
        root.bind_all("<Command-l>", lambda e: clear_spots())

        root.config(menu=menubar)

        # Standard macOS shortcut for Preferences
        root.bind_all("<Command-comma>", lambda e: self.open_settings())

        # Start threads
        cluster_thread = threading.Thread(target=cluster_listener, daemon=True)
        flex_thread = threading.Thread(target=flex_listener, daemon=True)
        cluster_thread.start()
        flex_thread.start()

    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Preferences")
        settings_win.geometry("400x300")

        # Settings fields
        settings = [
            ("FLEX_IP", "FLEX_IP"),
            ("FLEX_PORT", "FLEX_PORT"),
            ("CLUSTER_HOST", "CLUSTER_HOST"),
            ("CLUSTER_PORT", "CLUSTER_PORT"),
            ("CALLSIGN", "CALLSIGN"),
            ("SPOT_TIMEOUT", "SPOT_TIMEOUT"),
            ("FREQ_MATCH_HZ", "FREQ_MATCH_HZ"),
            ("FREQ_CHANGE_HZ", "FREQ_CHANGE_HZ"),
        ]

        entries = {}
        row = 0
        for label, var_name in settings:
            tk.Label(settings_win, text=f"{label}:").grid(row=row, column=0, sticky="e")
            entry = tk.Entry(settings_win)
            entry.insert(0, str(globals()[var_name]))
            entry.grid(row=row, column=1)
            entries[var_name] = entry
            row += 1

        def save():
            for var_name, entry in entries.items():
                value = entry.get()
                if var_name in ["FLEX_PORT", "CLUSTER_PORT", "SPOT_TIMEOUT", "FREQ_MATCH_HZ", "FREQ_CHANGE_HZ"]:
                    globals()[var_name] = int(value)
                else:
                    globals()[var_name] = value
            save_settings()
            settings_win.destroy()
            print("Settings saved")

        tk.Button(settings_win, text="OK", command=save).grid(row=row, column=1)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()