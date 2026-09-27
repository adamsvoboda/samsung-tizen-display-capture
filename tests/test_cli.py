from pathlib import Path
from contextlib import nullcontext
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from samsung_tizen_obs_input.cli import build_parser, main, sample, stream_config
from samsung_tizen_obs_input.config import Config


class CliTests(unittest.TestCase):
    def test_stop_and_inspection_do_not_upload_running_helper(self):
        config = Config.from_mapping({"monitor_ip": "192.0.2.10", "receiver_ip": "192.0.2.20"})
        for command in ("stop", "status", "logs"):
            with self.subTest(command=command), patch("samsung_tizen_obs_input.cli.Config.load", return_value=config), \
                    patch("samsung_tizen_obs_input.cli.sdb_transport", return_value=nullcontext()), \
                    patch("samsung_tizen_obs_input.cli.SdbBridge") as bridge:
                bridge.return_value.dispatch.return_value = "ok"
                self.assertEqual(main([command]), 0)
                bridge.return_value.stage.assert_not_called()

    def test_command_overrides_preserve_saved_settings(self):
        original = Config.from_mapping({"monitor_ip": "192.0.2.10", "receiver_ip": "192.0.2.20"})
        args = build_parser().parse_args(["start", "--bitrate", "12", "--mute", "--fps", "30"])
        updated = stream_config(original, args)
        self.assertEqual(updated.quality_mode, "high")
        self.assertEqual(updated.video_bitrate_mbps, 12)
        self.assertFalse(updated.audio_enabled)
        self.assertEqual(updated.fps, 30)
        self.assertTrue(original.audio_enabled)
        self.assertEqual(original.video_bitrate_mbps, 8)

    def test_loopback_sample_and_no_overwrite(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = Config(monitor_ip="127.0.0.1", receiver_ip="127.0.0.1", port=port)
        bridge = Mock()
        bridge.stream_args.return_value = ()

        def dispatch(action, *args, **kwargs):
            if action == "sample":
                with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                    connection.sendall(b"test transport bytes")

        bridge.dispatch.side_effect = dispatch
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sample.ts"
            with patch("samsung_tizen_obs_input.cli._probe_media") as verify:
                sample(bridge, config, 1, output)
            verify.assert_called_once_with(output, config)
            self.assertEqual(output.read_bytes(), b"test transport bytes")
            with self.assertRaises(FileExistsError):
                sample(bridge, config, 1, output)
            self.assertEqual(output.read_bytes(), b"test transport bytes")
