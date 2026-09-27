# Configuration and troubleshooting

Commands below use `tizen-obs` as shorthand. From a local virtual environment use `.\.venv\Scripts\tizen-obs.exe` on Windows, or `.venv/bin/tizen-obs` on macOS/Linux. Run from the project folder, or use `--config PATH` before the subcommand.

## Settings

[config.example.json](../config.example.json) lists the available settings. `configure` writes a local file; do not publish it. Command-line options apply to one invocation and do not rewrite saved settings.

- `monitor_ip`: display IPv4 address; `receiver_ip`: computer IPv4 address reachable from it.
- `port`: TCP receiver port, default 26470. Use a DHCP reservation to keep addresses stable.
- `control_port`: TCP port for short command replies, default 26471. It must differ from the video port. Permit both local ports from the display through any host or guest-network firewall.
- `sdb_path`: installed SDB executable, including paths with spaces. Enter it without shell quotes in the setup prompt. JSON uses escaped backslashes; forward slashes also work in Windows paths.
- `quality_mode`: `standard` (1–8 Mbps) or `high` (9–30 Mbps). Default bitrate is 8 for standard or 12 for high if omitted. `--bitrate` selects the appropriate mode automatically.
- `resolution` / `fps`: 1920x1080 / 60 by default. 1280x720 and 30 fps are experimental.
- `audio_enabled`, `audio_bitrate_kbps`, `audio_source`: audio on by default, 192 kbps, `tizenaudio-sink.monitor`. The source is monitor playback audio, not independently selected HDMI audio.

Capture always follows the active display; input selection and inactive HDMI capture are unsupported.

Stop the current stream before changing output settings. A running stream keeps its previous settings.

## Isolated networks

For direct SDB, leave `sdb_ssh_host` empty and use the display IP with port 26101 as `sdb_target`. The display needs Developer Mode access; an interactive SDB shell is not required.

For an existing SSH relay, set `sdb_ssh_host` to a user/host such as `user@router.local`. Set `sdb_target` to `127.0.0.1:26101` (or another free local port). The controller opens and closes that SSH forward per command. SSH keys and known-host trust must already work; passwords and credentials are not stored here. The display's Developer Mode host address must match the relay address seen by the display.

Windows users need [OpenSSH Client](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse) only when using this option. The controller does not need the SSH server component. Video and control replies go directly from display to computer, separately from SDB. Permit the configured TCP video and control ports through your computer firewall; on Windows allow the receiving application on the Private network profile. Guest networks need narrow display-to-computer rules for both ports.

## OBS behavior

OBS's [Media Source](https://obsproject.com/kb/media-sources) accepts the printed TCP URL with input format `mpegts`. Keep the source listening before starting capture. If a source is deactivated or its connection closes, reactivate it and restart the display stream. Process `status` does not prove OBS is showing video.

Start with 2 MB Network Buffering. Reduce only if playback stays stable; increase if network jitter causes stutter. Buffer size does not set encoding quality. Keep OBS's mixer meter visible and use one audio path to avoid echo or comb filtering. Set sync offset only after measuring an actual audio/video delay. No end-to-end latency, HDR, or color-fidelity guarantee has been established.

Streamlabs Desktop has [network Media Sources](https://support.streamlabs.com/hc/en-us/articles/360044481813-Mobile-LAN-Streaming-Source-Guide), but this TCP listener/MPEG-TS combination has not been verified there.

## FFmpeg and samples

Start the FFmpeg listener in one terminal, then `tizen-obs start` in another:

```sh
ffmpeg -i "tcp://COMPUTER_IP:26470?listen=1" -c copy recording.mkv
```

This copies the received encoded audio/video without another compression pass. Stop the display stream, then end FFmpeg. Replace the placeholder computer IP with the receiver address. OBS and FFmpeg cannot both own the same listener port.

`tizen-obs sample --seconds 10 --output test.ts` runs its own listener and checks codec, requested resolution/frame-rate metadata, and full decoding if FFmpeg is installed. It never overwrites an existing file. A failure may leave a partial sample for diagnosis. The reported frame-rate metadata is not a visual proof of unique frames at that cadence.

Use `doctor` for SDB launch and media components, `logs` for media errors, and `status` for the encoder process. If `doctor` receives no control reply, check the configured control port, routing, and firewall. If 48 kHz audio negotiation fails, see [audio limitations](audio.md) rather than assuming resampling restores fidelity.
