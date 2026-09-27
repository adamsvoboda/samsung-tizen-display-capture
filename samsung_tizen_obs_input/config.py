"""Local configuration; never include a user's config in a release."""

from dataclasses import asdict, dataclass
import ipaddress
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional


DEFAULT_CONFIG = Path("config.json")
_AUDIO_SOURCE = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_SDB_TARGET = re.compile(r"(?:[A-Za-z0-9_.-]+)(?::[0-9]{1,5})?\Z")
_SSH_HOST = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


class ConfigError(ValueError):
    """A setting cannot be used safely or will not reach the receiver."""


def _ipv4(value: Any, name: str) -> str:
    try:
        address = ipaddress.IPv4Address(str(value))
    except ipaddress.AddressValueError as exc:
        raise ConfigError(f"{name} must be an IPv4 address") from exc
    if address.is_unspecified or address.is_multicast or address.is_loopback:
        raise ConfigError(f"{name} must be a reachable unicast IPv4 address")
    return str(address)


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


@dataclass(frozen=True)
class Config:
    monitor_ip: str
    receiver_ip: str
    port: int = 26470
    control_port: int = 26471
    sdb_target: Optional[str] = None
    sdb_path: str = "sdb"
    sdb_ssh_host: Optional[str] = None
    quality_mode: str = "standard"
    video_bitrate_mbps: int = 8
    audio_source: str = "tizenaudio-sink.monitor"
    resolution: str = "1920x1080"
    fps: int = 60
    audio_enabled: bool = True
    audio_bitrate_kbps: int = 192

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "Config":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise ConfigError("Unknown setting(s): " + ", ".join(sorted(unknown)))
        try:
            monitor_ip = _ipv4(values["monitor_ip"], "monitor_ip")
            receiver_ip = _ipv4(values["receiver_ip"], "receiver_ip")
        except KeyError as exc:
            raise ConfigError(f"Missing required setting: {exc.args[0]}") from exc
        if monitor_ip == receiver_ip:
            raise ConfigError("monitor_ip and receiver_ip must be different")

        port = _integer(values.get("port", 26470), "port", 1024, 65535)
        control_port = _integer(values.get("control_port", 26471), "control_port", 1024, 65535)
        if control_port == port:
            raise ConfigError("control_port and port must be different")
        quality_mode = values.get("quality_mode", "standard")
        if not isinstance(quality_mode, str) or quality_mode not in {"standard", "high"}:
            raise ConfigError("quality_mode must be 'standard' or 'high'")
        bitrate = _integer(values.get("video_bitrate_mbps", 12 if quality_mode == "high" else 8), "video_bitrate_mbps",
                           9 if quality_mode == "high" else 1,
                           30 if quality_mode == "high" else 8)
        audio = values.get("audio_source", "tizenaudio-sink.monitor")
        if not isinstance(audio, str) or not _AUDIO_SOURCE.fullmatch(audio):
            raise ConfigError("audio_source may contain only letters, digits, '.', '_' and '-'")
        sdb_path = values.get("sdb_path", "sdb")
        if not isinstance(sdb_path, str) or not sdb_path.strip():
            raise ConfigError("sdb_path must name the installed SDB executable")
        ssh_host = values.get("sdb_ssh_host")
        if ssh_host == "":
            ssh_host = None
        if ssh_host is not None and (not isinstance(ssh_host, str) or
                                     not _SSH_HOST.fullmatch(ssh_host)):
            raise ConfigError("sdb_ssh_host must be a host or user@host")
        target = values.get("sdb_target")
        if target is None or target == "":
            target = "127.0.0.1:26101" if ssh_host else f"{monitor_ip}:26101"
        if not isinstance(target, str) or not _SDB_TARGET.fullmatch(target):
            raise ConfigError("sdb_target must be a host or host:port")
        if ":" not in target:
            target += ":26101"
        if ":" in target:
            target_port = int(target.rsplit(":", 1)[1])
            if not 1 <= target_port <= 65535:
                raise ConfigError("sdb_target port must be from 1 to 65535")
        if ssh_host and not re.fullmatch(r"(?:127\.0\.0\.1|localhost):[0-9]{1,5}", target):
            raise ConfigError("With sdb_ssh_host, sdb_target must be localhost:PORT")
        resolution = values.get("resolution", "1920x1080")
        if resolution not in ("1920x1080", "1280x720"):
            raise ConfigError("resolution must be 1920x1080 or 1280x720 (experimental)")
        fps = _integer(values.get("fps", 60), "fps", 30, 60)
        if fps not in (30, 60):
            raise ConfigError("fps must be 30 (experimental) or 60")
        audio_enabled = values.get("audio_enabled", True)
        if not isinstance(audio_enabled, bool):
            raise ConfigError("audio_enabled must be true or false")
        audio_bitrate = _integer(values.get("audio_bitrate_kbps", 192), "audio_bitrate_kbps", 128, 256)
        if audio_bitrate not in (128, 192, 256):
            raise ConfigError("audio_bitrate_kbps must be 128, 192, or 256")
        return cls(monitor_ip=monitor_ip, receiver_ip=receiver_ip, port=port,
                   control_port=control_port,
                   sdb_target=target, sdb_path=sdb_path, sdb_ssh_host=ssh_host,
                   quality_mode=quality_mode, video_bitrate_mbps=bitrate, audio_source=audio,
                   resolution=resolution, fps=fps, audio_enabled=audio_enabled,
                   audio_bitrate_kbps=audio_bitrate)

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"No {path}; run 'tizen-obs configure' first") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(values, dict):
            raise ConfigError(f"{path} must contain a JSON object")
        return cls.from_mapping(values)

    def save(self, path: Path) -> None:
        try:
            with path.open("x", encoding="utf-8", newline="\n") as output:
                output.write(json.dumps(asdict(self), indent=2) + "\n")
        except FileExistsError as exc:
            raise ConfigError(f"{path} already exists; edit it or choose another --config path") from exc
        try:
            path.chmod(0o600)
        except OSError:
            pass

    @property
    def obs_url(self) -> str:
        return f"tcp://{self.receiver_ip}:{self.port}?listen=1"

    @property
    def dimensions(self) -> tuple:
        return tuple(map(int, self.resolution.split("x")))
