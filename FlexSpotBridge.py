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
import webbrowser

APP_NAME = "FlexSpotBridge"
APP_VERSION = "1.0 beta"
APP_REVISION = 1


def app_version_label():
    return f"{APP_VERSION} (rev {APP_REVISION})"


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
FREQ_MATCH_HZ = 100

# Minimum frequency change to trigger spot detection (Hz)
FREQ_CHANGE_HZ = 200

# If True, do not change slice mode when a spot is matched.
KEEP_CURRENT_MODE = False

# If True, show high-volume debug logging in the UI log window.
VERBOSE_LOGGING = False

# Storage for cluster spots
spots = []

# Track Flex panadapter spots by spot ID -> frequency (Hz)
flex_spots = {}
flex_spots_lock = threading.Lock()

# Treat spots within this delta as same frequency on Flex (Hz)
FLEX_SPOT_SAME_FREQ_HZ = 1


def send_flex_command(command):
    """Send a one-shot command to the Flex API."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLEX_IP, FLEX_PORT))
    sock.sendall(f"C1|{command}\n".encode())
    sock.close()


def log_debug(*args, **kwargs):
    if VERBOSE_LOGGING:
        print(*args, **kwargs)


def remove_duplicate_flex_spots(freq, keep_spot_id, command_sock=None):
    """Remove older Flex panadapter spots at the same frequency, keeping one ID."""
    with flex_spots_lock:
        duplicate_ids = [
            spot_id
            for spot_id, spot_freq in flex_spots.items()
            if spot_id != keep_spot_id and abs(spot_freq - freq) <= FLEX_SPOT_SAME_FREQ_HZ
        ]

        for spot_id in duplicate_ids:
            flex_spots.pop(spot_id, None)

    for spot_id in duplicate_ids:
        try:
            if command_sock is None:
                send_flex_command(f"spot remove {spot_id}")
            else:
                command_sock.sendall(f"C3|spot remove {spot_id}\n".encode())
            print(f"Removed older Flex spot id={spot_id} at {freq} Hz")
        except Exception as e:
            print(f"Failed to remove Flex spot id={spot_id}: {e}")

# ------------------------------------------------
# SETTINGS PERSISTENCE
# ------------------------------------------------

SETTINGS_FILE = os.path.expanduser("~/Library/Preferences/FlexSpotBridge.json")

def load_settings():
    global FLEX_IP, FLEX_PORT, CLUSTER_HOST, CLUSTER_PORT, CALLSIGN, SPOT_TIMEOUT, FREQ_MATCH_HZ, FREQ_CHANGE_HZ, KEEP_CURRENT_MODE, VERBOSE_LOGGING
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
            KEEP_CURRENT_MODE = bool(data.get("KEEP_CURRENT_MODE", KEEP_CURRENT_MODE))
            VERBOSE_LOGGING = bool(data.get("VERBOSE_LOGGING", VERBOSE_LOGGING))
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
            "KEEP_CURRENT_MODE": KEEP_CURRENT_MODE,
            "VERBOSE_LOGGING": VERBOSE_LOGGING,
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
    log_debug(f"Checking {len(spots)} spots for freq {freq}")

    # Iterate newest-first so latest spot wins when multiple match.
    for spot in reversed(spots):

        if now - spot["time"] > SPOT_TIMEOUT:
            continue

        log_debug("Checking spot:", spot["call"], spot["freq"],
                  "diff:", abs(spot["freq"] - freq))

        if abs(spot["freq"] - freq) <= FREQ_MATCH_HZ:
            log_debug("Latest matching spot selected:", spot["call"], spot["freq"])
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

            log_debug("Cluster:", line)

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

                # Keep only the latest spot per exact frequency in local cache.
                before_count = len(spots)
                spots[:] = [spot for spot in spots if spot["freq"] != freq]
                removed_count = before_count - len(spots)
                if removed_count:
                    log_debug(f"Removed {removed_count} older spot(s) at {freq} Hz")

                spots.append({
                    "freq": freq,
                    "call": call,
                    "time": time.time()
                })

                log_debug("Spot stored:", call, freq)

                # check if radio already tuned to this spot
                global current_freq

                if current_freq is not None:

                    diff = abs(current_freq - freq)

                    log_debug("Checking current freq:", current_freq,
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
    sock.sendall(b"C2|sub spot all\n")

    while True:

        data = sock.recv(4096).decode(errors="ignore")
        
        log_debug("Flex data:", data.strip())

        if not data:
            continue

        for line in data.splitlines():
            spot_match = re.search(
                r"S[^|]+\|spot\s+(\d+).*?(?:rx_freq|freq)=(\d+(?:\.\d+)?)",
                line
            )
            if spot_match:
                spot_id = spot_match.group(1)
                spot_freq = float(spot_match.group(2)) * 1e6
                with flex_spots_lock:
                    flex_spots[spot_id] = spot_freq
                remove_duplicate_flex_spots(spot_freq, spot_id, command_sock=sock)

            removed_match = re.search(r"S[^|]+\|spot\s+removed\s+(\d+)", line)
            if removed_match:
                removed_id = removed_match.group(1)
                with flex_spots_lock:
                    flex_spots.pop(removed_id, None)

        m = re.search(r"S[^|]+\|slice\s+(\d+).*RF_frequency=(\d+\.\d+)", data)
        
        if m:
        
            slice_id = m.group(1)
            
            freq = float(m.group(2)) * 1e6
            global current_freq
            previous_freq = current_freq

            log_debug("Current frequency:", freq)

            # Compare each update to the immediately previous frequency.
            if previous_freq is None:
                freq_change = 0
                log_debug("Initial frequency captured; waiting for next change to evaluate threshold")
            else:
                freq_change = abs(freq - previous_freq)

                if freq_change >= FREQ_CHANGE_HZ:
                    log_debug(f"Frequency change: {freq_change} Hz (threshold: {FREQ_CHANGE_HZ} Hz)")

                    call = find_spot(freq)

                    if call:
                        print("Matched spot:", call)

                        set_mldx_call(call)

                        if KEEP_CURRENT_MODE:
                            print("Keep current mode is enabled; not changing mode")
                        else:
                            auto_mode(sock, slice_id, freq)
                else:
                    log_debug(f"Frequency change: {freq_change} Hz - below threshold ({FREQ_CHANGE_HZ} Hz), skipping spot check")

            # Always update baseline frequency for the next incoming change.
            current_freq = freq
            
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
        self.root.title(f"{APP_NAME} {app_version_label()}")
        self.root.geometry("600x400")

        self.text = tk.Text(root, wrap=tk.WORD)
        self.text.pack(expand=True, fill=tk.BOTH)

        # Redirect stdout
        sys.stdout = TextRedirector(self.text)
        print(f"{APP_NAME} {app_version_label()} starting...")

        # Menu
        menubar = tk.Menu(root)

        # App menu (standard macOS layout: Preferences + Quit)
        appmenu = tk.Menu(menubar, name='apple')


        def clear_spots():
            # Send 'spot clear' to Flex API
            try:
                send_flex_command("spot clear")
                global current_freq
                removed_spots = len(spots)
                spots.clear()
                with flex_spots_lock:
                    flex_spots.clear()
                current_freq = None
                print(f"All spots cleared on Flex panadapter. Local spot memory reset ({removed_spots} spots removed).")
            except Exception as e:
                print(f"Failed to clear spots on Flex: {e}")


        appmenu.add_command(label=f"About {APP_NAME}", command=self.open_about)
        appmenu.add_separator()
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

    def open_about(self):
        about_win = tk.Toplevel(self.root)
        about_win.title(f"About {APP_NAME}")
        dialog_width = 520
        dialog_height = 320
        about_win.geometry(f"{dialog_width}x{dialog_height}")
        about_win.resizable(False, False)
        about_win.transient(self.root)

        # Center over the main app window.
        self.root.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        pos_x = root_x + max((root_w - dialog_width) // 2, 0)
        pos_y = root_y + max((root_h - dialog_height) // 2, 0)
        about_win.geometry(f"{dialog_width}x{dialog_height}+{pos_x}+{pos_y}")

        # Give the dialog a bold, colorful look while keeping it lightweight.
        about_win.configure(bg="#FFF4D6")

        outer = tk.Frame(about_win, bg="#FFF4D6", padx=20, pady=20)
        outer.pack(expand=True, fill=tk.BOTH)

        banner = tk.Frame(outer, bg="#0A3D62", padx=16, pady=12)
        banner.pack(fill=tk.X, pady=(0, 14))

        banner_top = tk.Frame(banner, bg="#0A3D62")
        banner_top.pack(fill=tk.X)

        badge = tk.Canvas(
            banner_top,
            width=54,
            height=54,
            bg="#0A3D62",
            highlightthickness=0,
            bd=0
        )
        badge.create_oval(3, 3, 51, 51, fill="#F0932B", outline="#F6E58D", width=2)
        badge.create_text(27, 27, text="FSB", fill="#0A3D62", font=("Avenir Next", 12, "bold"))
        badge.pack(side=tk.LEFT, padx=(0, 12))

        title_box = tk.Frame(banner_top, bg="#0A3D62")
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            title_box,
            text=APP_NAME,
            font=("Avenir Next", 22, "bold"),
            fg="#F6E58D",
            bg="#0A3D62"
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text=f"Version {app_version_label()}",
            font=("Avenir Next", 12, "bold"),
            fg="#DFF9FB",
            bg="#0A3D62"
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(outer, bg="#FFFFFF", padx=16, pady=14, highlightthickness=2, highlightbackground="#F0932B")
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Created by Bill Cody, K3CDY",
            font=("Avenir Next", 13),
            fg="#130F40",
            bg="#FFFFFF"
        ).pack(anchor="w", pady=(0, 8))

        github_url = "https://github.com/williamscody/FlexSpotBridge"

        tk.Label(
            body,
            text=github_url,
            font=("Menlo", 12),
            fg="#0652DD",
            bg="#FFFFFF",
            cursor="hand2"
        ).pack(anchor="w")

        def open_github(_event=None):
            webbrowser.open(github_url)

        body.bind("<Button-1>", open_github)
        for child in body.winfo_children():
            if isinstance(child, tk.Label) and child.cget("text") == github_url:
                child.bind("<Button-1>", open_github)

        tk.Button(
            outer,
            text="Close",
            command=about_win.destroy,
            bg="#22A6B3",
            fg="white",
            activebackground="#1B9AA6",
            activeforeground="white",
            relief=tk.FLAT,
            padx=16,
            pady=6
        ).pack(anchor="e", pady=(12, 0))

        about_win.grab_set()
        about_win.focus_set()

    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Preferences")
        settings_win.geometry("400x380")

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

        keep_current_mode_var = tk.BooleanVar(value=KEEP_CURRENT_MODE)
        tk.Checkbutton(
            settings_win,
            text="Keep current mode",
            variable=keep_current_mode_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 8))
        row += 1

        verbose_logging_var = tk.BooleanVar(value=VERBOSE_LOGGING)
        tk.Checkbutton(
            settings_win,
            text="Verbose debug logging",
            variable=verbose_logging_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        row += 1

        def save():
            global KEEP_CURRENT_MODE, VERBOSE_LOGGING
            for var_name, entry in entries.items():
                value = entry.get()
                if var_name in ["FLEX_PORT", "CLUSTER_PORT", "SPOT_TIMEOUT", "FREQ_MATCH_HZ", "FREQ_CHANGE_HZ"]:
                    globals()[var_name] = int(value)
                else:
                    globals()[var_name] = value
            KEEP_CURRENT_MODE = keep_current_mode_var.get()
            VERBOSE_LOGGING = verbose_logging_var.get()
            save_settings()
            settings_win.destroy()
            print("Settings saved")

        tk.Button(settings_win, text="OK", command=save).grid(row=row, column=1)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()