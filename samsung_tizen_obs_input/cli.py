"""Command line controller for a local Samsung display MPEG-TS stream."""

import argparse
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Dict, Optional

from . import __version__
from .bridge import BridgeError, SdbBridge, sdb_transport
from .config import Config, ConfigError, DEFAULT_CONFIG


def _ask(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or (default or "")


def configure(path: Path) -> None:
    print("Use the display's local IPv4 address and the computer IP that it can reach.")
    monitor_ip = _ask("Display IPv4 address")
    receiver_ip = _ask("This computer's reachable IPv4 address")
    ssh_host = _ask("SSH host for routed SDB (blank for direct connection)")
    values = {
        "monitor_ip": monitor_ip,
        "receiver_ip": receiver_ip,
        "port": int(_ask("TCP stream port", "26470")),
        "control_port": int(_ask("TCP control port", "26471")),
        "sdb_ssh_host": ssh_host or None,
        "sdb_target": _ask("SDB target", "127.0.0.1:26101" if ssh_host else f"{monitor_ip}:26101"),
        "sdb_path": _ask("SDB executable", "sdb"),
        "quality_mode": _ask("Quality mode: standard or high", "standard"),
        "audio_source": _ask("Display audio monitor", "tizenaudio-sink.monitor"),
    }
    high = values["quality_mode"] == "high"
    values["video_bitrate_mbps"] = int(_ask(
        "Video bitrate in Mb/s (standard 1-8; high 9-30)", "12" if high else "8"))
    Config.from_mapping(values).save(path)
    print(f"Saved {path}. Keep local device settings out of published sources.")


def _probe_media(path: Path, config: Config) -> None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        print("Install FFmpeg to verify the sample's codecs, resolution, and audio.")
        return
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration,bit_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise BridgeError("The sample did not parse as media: " + result.stderr.strip())
    details = json.loads(result.stdout)
    streams = details.get("streams", [])
    video = next((entry for entry in streams if entry.get("codec_name") == "h264"), None)
    audio = next((entry for entry in streams if entry.get("codec_name") == "aac"), None)
    if video is None or (config.audio_enabled and audio is None):
        raise BridgeError("The sample is missing the requested video or audio stream")
    if (video.get("width"), video.get("height")) != config.dimensions:
        raise BridgeError("The display did not produce the requested resolution")
    if Fraction(video.get("r_frame_rate", "0/1")) != config.fps:
        raise BridgeError("The display did not report the requested frame rate")
    print(
        f"Verified H.264 {video.get('width')}x{video.get('height')} "
        f"at {video.get('r_frame_rate')} fps" + (" with AAC audio" if audio else " without audio")
    )
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        decoded = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=45,
        )
        if decoded.returncode != 0 or decoded.stderr.strip():
            raise BridgeError("The sample did not decode cleanly: " + decoded.stderr[-800:])
        print("Full video and audio decode passed")


def sample(bridge: SdbBridge, config: Config, seconds: int, output: Path) -> None:
    errors: Dict[str, Exception] = {}

    def invoke() -> None:
        try:
            bridge.dispatch("sample", *bridge.stream_args(), str(seconds), timeout=seconds + 20)
        except Exception as exc:
            errors["dispatch"] = exc

    # Exclusive creation protects existing recordings from accidental overwrite.
    with output.open("xb") as destination, socket.socket() as listener:
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((config.receiver_ip, config.port))
            listener.listen(1)
            listener.settimeout(0.25)
        except OSError as exc:
            raise BridgeError(
                f"Cannot listen on {config.receiver_ip}:{config.port}. "
                "Close the OBS Media Source on this port before running sample."
            ) from exc
        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        deadline = time.monotonic() + seconds + 20
        connected = False
        try:
            while True:
                if "dispatch" in errors:
                    raise BridgeError(str(errors["dispatch"]))
                if time.monotonic() >= deadline:
                    raise BridgeError("No stream arrived; check routing, receiver firewall, and 'tizen-obs logs'")
                try:
                    connection, peer = listener.accept()
                    if peer[0] != config.monitor_ip:
                        connection.close()
                        continue
                    connected = True
                    break
                except socket.timeout:
                    continue
            with connection:
                connection.settimeout(1)
                while True:
                    if time.monotonic() >= deadline:
                        raise BridgeError("Sample exceeded its time limit")
                    try:
                        chunk = connection.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    destination.write(chunk)
                    if destination.tell() > 160 * 1024 * 1024:
                        raise BridgeError("Sample exceeded its 160 MB size limit")
        except BaseException:
            if connected and worker.is_alive():
                try:
                    bridge.dispatch("stop", timeout=8)
                except BridgeError:
                    pass
            raise
        finally:
            worker.join(timeout=max(0, deadline - time.monotonic()))
    if worker.is_alive():
        raise BridgeError("The display sample command did not finish")
    if "dispatch" in errors:
        raise BridgeError(str(errors["dispatch"]))
    if output.stat().st_size == 0:
        raise BridgeError("The display connected but sent no media bytes")
    print(f"Received {output.stat().st_size:,} bytes from {peer[0]} into {output}")
    _probe_media(output, config)


def add_stream_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bitrate", type=int, metavar="MBPS", help="video target, 1-30 Mbps; >8 selects high mode")
    parser.add_argument("--resolution", choices=("1920x1080", "1280x720"), help="720p is experimental")
    parser.add_argument("--fps", type=int, choices=(30, 60), help="30 fps is experimental")
    audio = parser.add_mutually_exclusive_group()
    audio.add_argument("--mute", dest="audio_enabled", action="store_false", default=None)
    audio.add_argument("--audio", dest="audio_enabled", action="store_true")
    parser.add_argument("--audio-bitrate", type=int, choices=(128, 192, 256), metavar="KBPS")


def stream_config(config: Config, args: argparse.Namespace) -> Config:
    values = asdict(config)
    for arg, key in (("resolution", "resolution"), ("fps", "fps"),
                     ("audio_enabled", "audio_enabled"), ("audio_bitrate", "audio_bitrate_kbps")):
        value = getattr(args, arg, None)
        if value is not None:
            values[key] = value
    bitrate = getattr(args, "bitrate", None)
    if bitrate is not None:
        values["quality_mode"] = "high" if bitrate > 8 else "standard"
        values["video_bitrate_mbps"] = bitrate
    return Config.from_mapping(values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="local JSON configuration (default: ./config.json)")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("configure", help="create a local configuration interactively")
    commands.add_parser("url", help="print the OBS/FFmpeg Media Source URL")
    add_stream_options(commands.add_parser("start", help="start the display's stream after OBS is listening"))
    commands.add_parser("stop", help="stop the display's stream")
    commands.add_parser("status", help="show whether the display encoder is running")
    commands.add_parser("logs", help="show the most recent display pipeline messages")
    commands.add_parser("doctor", help="check SDB command launch and display media components")
    sample_command = commands.add_parser("sample", help="record and verify a short stream")
    sample_command.add_argument("--seconds", type=int, default=8)
    sample_command.add_argument("--output", type=Path, default=Path("sample.ts"))
    add_stream_options(sample_command)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "configure":
            configure(args.config)
            return 0
        config = stream_config(Config.load(args.config), args)
        if args.command == "url":
            print(config.obs_url)
            return 0
        if args.command == "sample" and not 1 <= args.seconds <= 30:
            parser.error("--seconds must be from 1 to 30")
        if args.command == "sample" and args.output.exists():
            raise ConfigError(f"{args.output} already exists; choose a new --output path")
        if args.command in {"sample", "start"}:
            if config.resolution != "1920x1080" or config.fps != 60:
                print("Experimental output mode: validate a sample before using it live.")
            print(f"Display capture: {config.resolution}, {config.fps} fps, "
                  f"{config.video_bitrate_mbps} Mbps target; "
                  + (f"AAC {config.audio_bitrate_kbps} kbps" if config.audio_enabled else "audio off"))
        with sdb_transport(config):
            bridge = SdbBridge(config)
            bridge.connect()
            if args.command in {"start", "sample", "doctor"}:
                bridge.stage()
            if args.command == "start":
                print(bridge.dispatch("start", *bridge.stream_args()))
                print(f"OBS Input: {config.obs_url}  |  Input Format: mpegts")
            elif args.command == "stop":
                print(bridge.dispatch("stop"))
            elif args.command == "sample":
                sample(bridge, config, args.seconds, args.output)
            elif args.command == "doctor":
                print(bridge.dispatch("check", *bridge.stream_args()))
            elif args.command in {"status", "logs"}:
                print(bridge.dispatch(args.command))
        return 0
    except (ConfigError, BridgeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
