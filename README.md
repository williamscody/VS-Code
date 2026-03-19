# FlexSpotBridge

## Overview
The Windows version of SmartSDR has a feature missing from Mac SmartSDR.  When clicking on a panadapter spot in the Windows version, that spot information is sent out from the app for use by other applications.  That function is not present in Mac SmartSDR.

With this app, you can click on any spot that appears in your panadapter (as sent by Software Defined Connectors' (SDC) SKM Server or Telnet Server), which tunes your radio to that spot.  FlexSpotBridge keeps track of spots sent by the SDC server, reads the new frequency from the Flex, and determines if there is a spot at (or near) that frequency.  If so, the spot information is forwarded to MacLoggerDX and fills in the Call field.  This obviates the need to manually enter the callsign in MacLoggerDX and gives you immediate information about the spot.

FlexSpotBridge provides a GUI for monitoring (log output), settings, and clearing panadapter spots.

The spot "flow" is as follows:

SDC -> extra_cluster -> MacLoggerDX -> Mac SmartSDR Panadapter


## Features
- Monitors FlexRadio and SDC cluster in real time
- Automatically sends matched callsigns to MacLoggerDX
- Optional automatic mode switching based on band-plan ranges
- GUI window with live log output
- User-adjustable settings (radio IP, ports, callsign, etc.)
- Menu bar integration with Preferences and Clear All Spots (⌘L)

## System Requirements (my setup)
- macOS 12 or later (Apple Silicon or Intel)
- Python 3.9+ (tested with Python 3.14)
- FlexRadio 6000, 8000 or Aurora series (tested with Flex 8400)
- Software Defined Connectors (SDC) cluster running locally
- Mac SmartSDR app installed
- MacLoggerDX installed
- extra_cluster installed (located in the MacLoggerDX "Extras/Supporting Apps" folder).  Note: extra_cluster is not required unless you choose to grab CW spots decoded by SDC.
- py2app (for building the app)

## Settings Explained
- **FLEX_IP**: The IP address of your FlexRadio (e.g., `192.168.68.157`)
- **FLEX_PORT**: The FlexRadio TCP API port (default: `4992`)
- **CLUSTER_HOST**: Hostname or IP of your SDC cluster (default: `localhost`)
- **CLUSTER_PORT**: Port for SDC cluster (default: `7373`)
- **CALLSIGN**: Your callsign for cluster login (e.g., `K3CDY`)
- **SPOT_TIMEOUT**: How long (in seconds) a spot remains valid (default: `600`)
- **FREQ_MATCH_HZ**: Frequency tolerance (in Hz) for matching a spot (default: `1000`)
- **FREQ_CHANGE_HZ**:  How much VFO frquency change is required before attempting a match (default: `500`)
- **Keep current mode** (checkbox): When enabled, FlexSpotBridge will not change the slice mode when a spot is matched. When disabled, FlexSpotBridge can change mode automatically according to its band-plan logic.

## Recommended Defaults for CW Operators
- Enable **Keep current mode** in Preferences so FlexSpotBridge does not switch out of CW on a matched spot.
- Keep **FREQ_MATCH_HZ** at `1000` as a good starting point; increase slightly if your click-to-spot tuning often lands just outside matches.
- Keep **FREQ_CHANGE_HZ** at `500` to avoid unnecessary lookups from very small tuning movements.
- Keep **SPOT_TIMEOUT** at `600` seconds unless you want only very recent spots to match.

## Build Instructions
1. Ensure you have Python 3.9+ and `py2app` installed:
   ```sh
   pip install py2app
   ```
2. Place `FlexSpotBridge.py`, `setup.py`, and `FlexSpotBridge.icns` (optional, for icon) in the same folder.
3. Build the app:
   ```sh
   python3 setup.py py2app
   ```
4. The app will be created at `dist/FlexSpotBridge.app`.
5. (Optional) Codesign the app for macOS:
   ```sh
   codesign --force --deep --sign - dist/FlexSpotBridge.app
   ```
6. Double-click the app to launch.

## Usage
- Launch Mac SmartSDR
- Launch MacLoggerDX
- Launch extra_cluster.  Set dxcluster to "localhost" and port to "7373".  Enter your callsign, and enable auto-connect.  Leave other settings unchecked.
- Launch SDC and configure your Telnet Server.  The port should be set to "7373" and under "Additional", "Connect and Start SKM Server" should be enabled.  Set up and Start your Spotters if desired.  (I rely on the SKM Server to identify CW spots for me so I only see signals decoded at my QTH.)
- Launch FlexSpotBridge
- Use the **Preferences...** menu (⌘,) to enter your settings.
- In **Preferences...**, enable **Keep current mode** if you want to stay in your current mode (for example, to avoid switching out of CW).
- Use **Clear All Spots** (⌘L) to clear all spots from the panadapter.  FlexSpotBridge will only recognize spots that appear AFTER the program is launched.
- All log output appears in the main window.
- Note that MacLoggerDX will be in focus momentarily when a spot populates the call field.  Focus will quickly resume to the prior app after the spot is entered into MLDX.

## License
MIT License
