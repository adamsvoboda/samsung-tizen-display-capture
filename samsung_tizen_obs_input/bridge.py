"""Local SDB transport for a user-selected Developer Mode display."""

import base64
from contextlib import contextmanager
from pathlib import Path
import secrets
import shutil
import shlex
import socket
import subprocess
import tempfile
import threading
import time
from typing import Iterator, Sequence

from .config import Config


REMOTE_BASE = "/home/owner/share/tmp/sdk_tools"
REMOTE_DIR = REMOTE_BASE + "/tizen-obs-release"
REMOTE_SCRIPT = REMOTE_DIR + "/stream.sh"
REMOTE_HELPER = REMOTE_DIR + "/NativeStream"


class BridgeError(RuntimeError):
    """The selected display could not run a controller command."""


@contextmanager
def sdb_transport(config: Config) -> Iterator[None]:
    """Use direct SDB, or a short-lived SSH forward through a user-selected LAN host."""
    if not config.sdb_ssh_host:
        yield
        return
    ssh = shutil.which("ssh")
    if ssh is None:
        raise BridgeError("SSH is needed for sdb_ssh_host but was not found")
    local_port = int(config.sdb_target.rsplit(":", 1)[1])
    with socket.socket() as check:
        check.settimeout(0.2)
        if check.connect_ex(("127.0.0.1", local_port)) == 0:
            raise BridgeError("SDB tunnel port is already occupied; choose a free localhost port in sdb_target")
    process = subprocess.Popen(
        [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
         "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
         "-N", "-L", f"127.0.0.1:{local_port}:{config.monitor_ip}:26101",
         config.sdb_ssh_host],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise BridgeError("SSH SDB forward failed: " + process.stderr.read().strip())
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise BridgeError("SSH SDB forward did not open within six seconds")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        if process.stderr:
            process.stderr.close()


def shell_command(action: str, args: Sequence[str]) -> str:
    """Build a validated command for the display-side controller script."""
    if action not in {"start", "stop", "status", "sample", "check", "logs"}:
        raise BridgeError("Unsupported controller action")
    for value in args:
        if not value or not all(char.isascii() and (char.isalnum() or char in "._-") for char in value):
            raise BridgeError("Unsafe controller argument")
    # Retail firmware permits sourcing staged scripts but rejects executing them by path.
    # The subshell contains stream.sh's `exit` without losing the control reply.
    return "(" + shlex.join(["source", REMOTE_SCRIPT, action, *args]) + ")"


class SdbBridge:
    def __init__(self, config: Config):
        self.config = config
        self.sdb = shutil.which(config.sdb_path)
        if self.sdb is None:
            path = Path(config.sdb_path).expanduser()
            if path.is_file():
                self.sdb = str(path.resolve())
        if self.sdb is None:
            raise BridgeError(
                "Samsung SDB was not found. Install Tizen Studio and set sdb_path in config.json."
            )

    def _run(self, arguments: Sequence[str], timeout: int = 20) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.sdb, *arguments], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BridgeError(f"SDB failed: {exc}") from exc

    def connect(self) -> None:
        result = self._run(["connect", self.config.sdb_target])
        output = result.stdout + result.stderr
        if result.returncode != 0 or "failed" in output.lower():
            raise BridgeError(f"SDB could not connect to {self.config.sdb_target}: {output.strip()}")
        devices = self._run(["devices"])
        if devices.returncode != 0 or not any(
            line.split()[:2] == [self.config.sdb_target, "device"]
            for line in devices.stdout.splitlines()
        ):
            raise BridgeError(f"SDB device is not ready: {(devices.stdout + devices.stderr).strip()}")

    def _require_success(self, result: subprocess.CompletedProcess, operation: str) -> str:
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise BridgeError(f"{operation} failed: {output[-1200:]}")
        return output

    def _inject(self, command: str, token: str, timeout: int) -> subprocess.CompletedProcess:
        """Use the SDB app-install command path proven by the original capture prototype."""
        gated = f"/bin/mkdir /tmp/s-{token} 2>/dev/null&&{{ {command};}}"
        encoded = base64.b64encode(gated.encode("utf-8")).decode("ascii")
        argument = "0 appinstall tpk new2.tpk`printf${IFS}%s${IFS}" + encoded + "|base64${IFS}-d|bash`.tpk"
        if len(argument.encode("ascii")) > 510:
            raise BridgeError("SDB command exceeds the display's request limit")
        return self._run(["-s", self.config.sdb_target, "shell", argument], timeout)

    def _execute(self, command: str, timeout: int = 20) -> str:
        """Receive the display command's output on the dedicated local control port."""
        token = secrets.token_hex(8)
        request_path = f"{REMOTE_BASE}/.tizen-obs-{token}.sh"
        marker = f"TIZEN_OBS_EXIT_{token}:"
        with tempfile.TemporaryDirectory(prefix="tizen-obs-command-") as directory:
            command_file = Path(directory) / "command.sh"
            command_file.write_bytes((
                "#!/bin/bash\n"
                f"exec 3<>/dev/tcp/{self.config.receiver_ip}/{self.config.control_port} || exit 111\n"
                f"{{ {command}; }} >&3 2>&3\n"
                "status=$?\n"
                f"printf '\\n{marker}%s\\n' \"$status\" >&3\n"
                "exec 3>&-\n"
            ).encode("utf-8"))
            with socket.socket() as listener:
                try:
                    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    else:
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    listener.bind((self.config.receiver_ip, self.config.control_port))
                    listener.listen(1)
                    listener.settimeout(0.25)
                except OSError as exc:
                    raise BridgeError(
                        f"Cannot listen for display control on {self.config.receiver_ip}:"
                        f"{self.config.control_port}; close the process using that port"
                    ) from exc
                self._require_success(self._run([
                    "-s", self.config.sdb_target, "push", str(command_file), request_path
                ]), "Stage display command")
                state = {}

                def invoke() -> None:
                    try:
                        state["result"] = self._inject("source " + shlex.quote(request_path), token, timeout)
                    except BridgeError as exc:
                        state["error"] = exc

                worker = threading.Thread(target=invoke, daemon=True)
                worker.start()
                deadline = time.monotonic() + timeout
                received = bytearray()
                try:
                    while True:
                        if time.monotonic() >= deadline:
                            detail = state.get("error") or state.get("result")
                            if isinstance(detail, subprocess.CompletedProcess):
                                detail = (detail.stdout + detail.stderr).strip() or f"SDB exit {detail.returncode}"
                            elif detail is None:
                                detail = "no SDB response"
                            raise BridgeError(
                                f"No display control reply on {self.config.receiver_ip}:"
                                f"{self.config.control_port}; check routing and firewalls. SDB: {str(detail)[-300:]}"
                            )
                        try:
                            connection, address = listener.accept()
                        except socket.timeout:
                            continue
                        if address[0] != self.config.monitor_ip:
                            connection.close()
                            continue
                        with connection:
                            connection.settimeout(0.25)
                            while True:
                                if time.monotonic() >= deadline:
                                    raise BridgeError("Display control reply timed out")
                                try:
                                    chunk = connection.recv(65536)
                                except socket.timeout:
                                    continue
                                if not chunk:
                                    break
                                received.extend(chunk)
                                if len(received) > 256 * 1024:
                                    raise BridgeError("Display control reply exceeded 256 KB")
                        break
                finally:
                    worker.join(timeout=2)
                    # A cleanup failure must not hide the command result.
                    try:
                        self._inject("rm -f " + shlex.quote(request_path), secrets.token_hex(8), 8)
                    except BridgeError:
                        pass
        output = received.decode("utf-8", errors="replace")
        lines = output.rstrip().splitlines()
        if not lines or not lines[-1].startswith(marker):
            raise BridgeError("Display command returned no exit status: " + output[-1000:])
        status = lines[-1][len(marker):]
        if not status.isdigit():
            raise BridgeError("Display command returned an invalid exit status")
        body = "\n".join(lines[:-1]).strip()
        if int(status) != 0:
            raise BridgeError("Display command failed: " + body[-1200:])
        return body

    def stage(self) -> None:
        self._execute("mkdir -p " + shlex.quote(REMOTE_DIR))
        status = self._execute(
            "if test -f " + shlex.quote(REMOTE_SCRIPT) + "; then "
            + shell_command("status", []) + "; else printf 'Stream stopped\n'; fi"
        )
        if "stream running" in status.lower():
            raise BridgeError("Stop the running stream before updating its media helper or settings")
        local = Path(__file__).with_name("stream.sh")
        # Windows checkouts may use CRLF; the display's Bash script always needs LF.
        with tempfile.TemporaryDirectory(prefix="tizen-obs-") as directory:
            normalized = Path(directory) / "stream.sh"
            normalized.write_bytes(local.read_bytes().replace(b"\r\n", b"\n"))
            self._require_success(self._run(["-s", self.config.sdb_target, "push",
                                            str(normalized), REMOTE_SCRIPT]), "Stage display script")
        if self.config.quality_mode == "high":
            for suffix in ("dll", "runtimeconfig.json"):
                local_helper = Path(__file__).with_name("bin") / f"NativeStream.{suffix}"
                result = self._run(["-s", self.config.sdb_target, "push",
                                    str(local_helper), f"{REMOTE_HELPER}.{suffix}"])
                self._require_success(result, "Stage high-quality helper")
        required = [REMOTE_SCRIPT]
        if self.config.quality_mode == "high":
            required += [REMOTE_HELPER + ".dll", REMOTE_HELPER + ".runtimeconfig.json"]
        checks = " && ".join("test -s " + shlex.quote(path) for path in required)
        self._execute(checks)

    def dispatch(self, action: str, *args: str, timeout: int = 20) -> str:
        return self._execute(shell_command(action, args), timeout)

    def stream_args(self) -> tuple:
        return (
            self.config.receiver_ip,
            str(self.config.port),
            str(self.config.video_bitrate_mbps * 1_000_000),
            self.config.audio_source,
            self.config.quality_mode,
            str(self.config.dimensions[0]),
            str(self.config.dimensions[1]),
            str(self.config.fps),
            "1" if self.config.audio_enabled else "0",
            str(self.config.audio_bitrate_kbps),
        )
