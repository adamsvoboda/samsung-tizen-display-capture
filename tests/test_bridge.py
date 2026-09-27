import base64
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from samsung_tizen_obs_input.bridge import BridgeError, SdbBridge, shell_command
from samsung_tizen_obs_input.config import Config


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.config = Config.from_mapping({"monitor_ip": "192.0.2.10", "receiver_ip": "192.0.2.20"})

    def bridge(self, config=None):
        with patch("shutil.which", return_value=r"C:\Program Files\Tizen\sdb.exe"):
            return SdbBridge(config or self.config)

    def loopback_bridge(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = Config(monitor_ip="127.0.0.1", receiver_ip="127.0.0.1",
                        control_port=port, sdb_target="127.0.0.1:26101")
        return self.bridge(config)

    def fake_sdb(self, bridge, message, status=0):
        state = {"command": "", "sent": False}

        def run(args, timeout=20):
            if args[2] == "push":
                state["command"] = Path(args[3]).read_text()
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[2] == "shell":
                if not state["sent"]:
                    state["sent"] = True
                    token = re.search(r"TIZEN_OBS_EXIT_([0-9a-f]+):", state["command"]).group(1)
                    with socket.create_connection(("127.0.0.1", bridge.config.control_port)) as callback:
                        callback.sendall(f"{message}\nTIZEN_OBS_EXIT_{token}:{status}\n".encode())
                # The app-install request's code does not reflect the script's exit code.
                return subprocess.CompletedProcess(args, 1, "", "closed")
            raise AssertionError(args)

        return run, state

    def test_connect_requires_sdb_device_but_not_general_shell(self):
        bridge = self.bridge()
        with patch.object(bridge, "_run", side_effect=[
            subprocess.CompletedProcess([], 0, "connected", ""),
            subprocess.CompletedProcess([], 0, "192.0.2.10:26101 device\n", ""),
        ]) as run:
            bridge.connect()
        self.assertEqual(run.call_args_list[1].args[0], ["devices"])

    def test_device_errors_are_not_reported_as_success(self):
        bridge = self.loopback_bridge()
        run, _ = self.fake_sdb(bridge, "encoder error", status=1)
        with patch.object(bridge, "_run", side_effect=run):
            with self.assertRaisesRegex(BridgeError, "encoder error"):
                bridge.dispatch("start", *bridge.stream_args())

    def test_appinstall_exit_code_is_not_device_command_exit_code(self):
        bridge = self.loopback_bridge()
        run, state = self.fake_sdb(bridge, "Stream stopped")
        with patch.object(bridge, "_run", side_effect=run):
            self.assertEqual(bridge.dispatch("status"), "Stream stopped")
        self.assertIn("source", state["command"])

    def test_windows_executable_path_is_one_argument(self):
        bridge = self.bridge()
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "closed")) as run:
            bridge._inject("true", "0" * 16, 5)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], r"C:\Program Files\Tizen\sdb.exe")
        self.assertIn("appinstall tpk", args[0][-1])
        self.assertFalse(kwargs.get("shell", False))
        argument = args[0][-1]
        encoded = argument.split("new2.tpk`printf${IFS}%s${IFS}", 1)[1].split("|base64${IFS}-d|bash`", 1)[0]
        self.assertIn("true", base64.b64decode(encoded).decode())
        self.assertLessEqual(len(argument.encode()), 510)

    def test_device_script_is_staged_as_lf(self):
        bridge = self.bridge()
        staged = []

        def run(args, timeout=20):
            if "push" in args:
                staged.append(Path(args[3]).read_bytes())
            return subprocess.CompletedProcess(args, 0, "ok", "")

        with patch.object(bridge, "_execute", side_effect=["", "Stream stopped", ""]), \
             patch.object(bridge, "_run", side_effect=run):
            bridge.stage()
        self.assertEqual(len(staged), 1)
        self.assertNotIn(b"\r\n", staged[0])

    def test_staging_never_replaces_running_helper(self):
        bridge = self.bridge()
        with patch.object(bridge, "_execute", side_effect=["", "Stream running (PID 123)"]), \
             patch.object(bridge, "_run") as run:
            with self.assertRaisesRegex(BridgeError, "Stop the running stream"):
                bridge.stage()
        run.assert_not_called()

    def test_argument_contract_for_media_helper(self):
        args = self.bridge().stream_args()
        self.assertEqual(args[5:], ("1920", "1080", "60", "1", "192"))
        self.assertTrue(shell_command("start", args).startswith("(source "))

    @unittest.skipIf(sys.platform == "win32", "Display-side Bash does not run on Windows")
    @unittest.skipUnless(shutil.which("bash"), "Bash is needed to check the device script")
    def test_sourced_script_uses_its_own_directory(self):
        original = Path(__file__).parents[1] / "samsung_tizen_obs_input" / "stream.sh"
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "staged"
            staged.mkdir()
            script = staged / "stream.sh"
            script.write_bytes(original.read_bytes())
            (staged / "stream.log").write_text("staged log marker\n")
            result = subprocess.run(
                ["bash", "-c", "(source ./staged/stream.sh logs)"],
                cwd=directory, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "staged log marker")
