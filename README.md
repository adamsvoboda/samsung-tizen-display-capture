Use your Samsung display as a capture card/input source in OBS or other software! Built with GPT-6 Sol (xhigh).

# About

Modern Samsung displays run Tizen and use [SDB](https://docs.tizen.org/application/tizen-studio/common-tools/smart-development-bridge/), Tizen's development bridge. Like Android's ADB, it connects development tools to a device. This project stages a small controller through SDB and launches the display's native media encoder, which sends video and audio directly over your LAN, letting you pipe it into OBS or other software like ffmpeg.

The Python controller uses SDB to copy a script to the monitor and launch it through the SDB app-install command path; higher video bitrates also use a small .NET helper. On the monitor, a GStreamer pipeline reads the active display with `smsrcavsource`, encodes it as H.264 with `smsrcvideoenc`, and captures audio through `pulsesrc` for AAC encoding. `mpegtsmux` combines the tracks into an MPEG-TS stream, which `tcpclientsink` sends over the LAN to a listening OBS Media Source or another receiver. A separate TCP connection returns command results and logs to the Python controller.

# Compatibility and limits

* **1080p60** is the highest verified capture mode. Video defaults to **8 Mbps** and can be adjusted up to 30 Mbps.
* Capture follows **the active display**, including the game HUD and Samsung menus and overlays observed on the tested G80SD. If you can see it on your display, it's in the capture.
* Captured audio has shown a sharp loss of frequencies above roughly 8 kHz, including before OBS encoding. Although the track is 48 kHz stereo, full-band audio is not yet verified. [Audio findings and next checks](docs/audio.md).

> **Access requirement:** install Samsung's SDB client and enable Developer Mode with your computer's IP as the developer host. No interactive SDB shell setup is needed.

**Capture and command launch:** The [SDB app-install command injection reported by Bishop Fox (SVE-2025-50109)](https://bishopfox.com/blog/samsung-tizen-os-version-through-9-0) provides this controller with a way to run commands on retail firmware that blocks ordinary SDB shell access. The display's native media pipeline does the capture and streaming without using the injection once started. The current controller still uses the injection for setup and every `start`, `stop`, `status`, and other device command; it is more than a one-time setup shortcut. If firmware closes this path, another way to launch and control the same pipeline would need to be tested and implemented. [Possible adaptations and their limits](docs/compatibility.md#if-the-command-injection-is-patched).

**Firmware compatibility:** As of September 27, 2026, [Samsung's public TV security updates](https://security.samsungtv.com/securityUpdates) do not identify a firmware fix for this issue. A [separate test on another model](https://github.com/chris-ritsen/samsung-tv-root/blob/master/docs/research-notes/QN90F_REPRODUCTION.md) reports the same command injection working on a Tizen 9.0 build dated July 2026; this does not establish support for every later firmware or display. Run `tizen-obs doctor` on your display to check the current launch path and media components.

Media capture was tested on a 32-inch Odyssey OLED G8 **G80SD / LS32DG802SNXZA**, software **T-RSPDWWC-0090-2123.6**, using macOS. Both 8 and 12 Mbps samples decoded as 1080p60 H.264 with AAC; live start/stop also worked. Audio fidelity, alternate output modes, Windows/Linux device operation, and other display models remain unverified. See [compatibility and current limits](docs/compatibility.md).

# Set up

Install Python 3.9+ and Samsung's [Tizen Studio tools](https://developer.samsung.com/smarttv/develop/tools/tizen-studio.html), including `sdb` (`sdb.exe` on Windows). Enable Developer Mode using Samsung's [device guide](https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/tv-device.html). **You can stop following the instructions after inputting your computer's IP address into the monitor's dev mode setting and rebooting the monitor**.

Your computer and display need a local route; the display must reach TCP **26470** for video and **26471** for control replies on your computer. Internet access is not needed for capture.

Download the project, open a terminal in its folder, and run:

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\tizen-obs.exe configure
.\.venv\Scripts\tizen-obs.exe doctor
```

**macOS / Linux**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/tizen-obs configure
.venv/bin/tizen-obs doctor
```

Enter the display IP, this computer's reachable IP, and the installed SDB path. Local settings go in Git-ignored `config.json`. On Windows, paste the path to `sdb.exe` without surrounding quotes; spaces are supported. For guest networks, see [optional SSH forwarding](docs/configuration.md#isolated-networks).

# Add to OBS

1. Add **Media Source**, clear **Local File**, and paste the URL printed by `tizen-obs url` into **Input**.
2. Set **Input Format** to `mpegts`. Start with the default **2 MB Network Buffering** and leave hardware decoding off if it causes playback trouble.
3. Keep the source active, then run `tizen-obs start`. Run `tizen-obs stop` when finished. Use the full executable path shown above for each command.

Default settings request **1080p60, 8 Mbps video, 48 kHz stereo AAC at 192 kbps**. Use `tizen-obs start --bitrate 12` for the higher bitrate mode; it requires the display's .NET 6 runtime. Buffering affects playback latency, not encoder quality. Avoid capturing the same audio again through Desktop Audio or monitoring it back into the recording.

| Control | Example | Notes |
| --- | --- | --- |
| Video bitrate | `start --bitrate 12` | 1–30 Mbps; clean short samples at 8, 12, 20, 30. |
| Output size / rate | `start --resolution 1280x720 --fps 30` | Experimental; 1080p60 is verified. No 1440p/4K mode. |
| Audio | `start --mute` or `start --audio-bitrate 256` | AAC 128/192/256 kbps; changing bitrate does not fix missing frequencies. |
| Diagnose | `doctor`, `status`, `logs` | Access/components, process state, and device log. |
| Check a sample | `sample --seconds 10 --output test.ts` | Close OBS's listener first; install FFmpeg for codec/decode checks. |

[Configuration and troubleshooting](docs/configuration.md) · [Build the helper](docs/development.md) · [MIT license](LICENSE)
