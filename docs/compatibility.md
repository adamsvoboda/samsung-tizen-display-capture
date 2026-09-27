# Compatibility and evidence

| Component | Evidence |
| --- | --- |
| Display media path | G80SD `LS32DG802SNXZA`, `T-RSPDWWC-0090-2123.6`: 1920×1080, 60 fps, H.264 and AAC decoded successfully. |
| Visible content | The user confirmed game content, game HUD, and Samsung menus in OBS. Capture follows the active display. Protected content or special overlays may differ. |
| Inactive HDMI | Unsupported by this implementation. `avtype=1` is an internal media setting, not an HDMI port selector. |
| Bitrate | Standard property tops out near 8 Mbps. Native control produced clean short samples at 12/20/30 Mbps. A 40 Mbps sample had a decode error. Sustained high-rate stability is unverified. |
| Alternate output modes | 720p and 30 fps controls are experimental. API ranges alone do not prove complete image, cadence, or audio behavior. |
| SDB launcher | On the tested retail G80SD build, SDB connects but ordinary shell commands are rejected. The app-install command path launches the staged script. `doctor`, 8 and 12 Mbps samples, and live start/stop passed on that display. |
| Host platforms | Earlier capture tests used macOS. Python code supports Windows/macOS/Linux; Windows/Linux execution still needs CI and device validation. No host Bash, WSL, or administrator terminal is required by the controller. |
| Other OBS clients | OBS Studio Media Source was used previously. Streamlabs and other clients are untested. |

## Developer Mode and command launch

SDB connectivity and an unrestricted interactive shell are distinct capabilities. Samsung's [testing FAQ](https://developer.samsung.com/smarttv/develop/faq/application-testing.html) describes restrictions on SDB access. This controller stages its own scripts through SDB file transfer and starts them using the [app-install command injection documented by Bishop Fox](https://bishopfox.com/blog/samsung-tizen-os-version-through-9-0) (SVE-2025-50109). The tested G80SD accepts this path despite rejecting an ordinary SDB shell. A firmware fix could close it; `doctor` checks the launch path and media components on the selected display. Command replies use a separate local TCP port (26471 by default), so status and stop remain available while OBS owns the video port.

This project supplies its own controller and media helper. It does not supply vendor firmware, vendor libraries, credentials, or device keys. Native media libraries and, for high mode, .NET 6 must already be present on the display.

## If the command injection is patched

The injection is a command launcher, not part of the GStreamer capture or MPEG-TS stream. The current controller uses it each time it creates the remote work directory or runs `check`, `start`, `stop`, `status`, `logs`, or `sample`. SDB file transfer alone can stage the scripts but cannot run them. A stream that is already running does not need the injection for each video frame, but the controller needs a working launcher for later commands and restarts.

On a display that permits ordinary `sdb shell` commands, the host bridge could replace its injection call with a direct shell invocation of the staged command script while retaining the media pipeline and control reply path. This requires testing that the shell account can access the same media components. It is not a fallback on the tested G80SD: ordinary shell requests are rejected there, consistent with [Samsung's note that TV devices lack SDB shell support](https://developer.samsung.com/tizen/blog/en/2020/07/20/installing-net-diagnostic-tools-on-tizen-devices).

Another device-specific command channel, such as separately available shell access, could run the same script if it has the required permissions. A packaged TV application would require separate investigation: Samsung's [TV app documentation](https://developer.samsung.com/smarttv/develop/faq/other-features.html) says application screen capture is unsupported, so a standard app is not a demonstrated replacement for this native pipeline. No alternate launcher has been implemented or verified for this project. If `doctor` fails after a firmware update, SDB connectivity or a successful file push alone does not establish that capture can be started.

## Resolution and bandwidth

The installed capture plugins report a 1920×1080 destination ceiling. A 4K display or input signal does not establish 4K encoding support. There is no demonstrated 1440p/4K capture route in this project.

Sequential roughly 10-second movie samples at requested 8/12/20/30 Mbps averaged about 2.5/9.8/15.0/23.6 Mbps of H.264 payload. These are changing scenes, not a calibrated quality comparison. Audio and transport add overhead; allow network headroom.

The source is TCP push: the display connects to the receiver's listener. One receiver can own a port at a time. The stream is local and unencrypted; keep it within a trusted LAN and avoid port forwarding it to the Internet.
