import tempfile
import unittest
from pathlib import Path

from samsung_tizen_obs_input.bridge import BridgeError, shell_command
from samsung_tizen_obs_input.config import Config, ConfigError


BASE = {
    "monitor_ip": "192.0.2.10",
    "receiver_ip": "192.0.2.20",
}


class ConfigTests(unittest.TestCase):
    def test_standard_and_high_ranges(self):
        standard = Config.from_mapping(BASE)
        self.assertEqual(standard.video_bitrate_mbps, 8)
        self.assertEqual(standard.quality_mode, "standard")
        self.assertEqual(standard.control_port, 26471)
        high = Config.from_mapping({**BASE, "quality_mode": "high", "video_bitrate_mbps": 30})
        self.assertEqual(high.video_bitrate_mbps, 30)
        for values in (
            {**BASE, "video_bitrate_mbps": 9},
            {**BASE, "quality_mode": "high", "video_bitrate_mbps": 8},
            {**BASE, "quality_mode": "high", "video_bitrate_mbps": 40},
        ):
            with self.subTest(values=values), self.assertRaises(ConfigError):
                Config.from_mapping(values)

    def test_rejects_shell_metacharacters_before_dispatch(self):
        with self.assertRaises(ConfigError):
            Config.from_mapping({**BASE, "audio_source": "audio;touch /tmp/x"})
        with self.assertRaises(ConfigError):
            Config.from_mapping({**BASE, "sdb_target": "host;echo x"})
        with self.assertRaises(ConfigError):
            Config.from_mapping({**BASE, "sdb_ssh_host": "root@host;echo x"})
        with self.assertRaises(ConfigError):
            Config.from_mapping({**BASE, "sdb_ssh_host": 0})
        with self.assertRaises(BridgeError):
            shell_command("start", ["192.0.2.20", "26470", "bad;argument"])

    def test_round_trip_local_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = Config.from_mapping({**BASE, "quality_mode": "high", "video_bitrate_mbps": 12})
            config.save(path)
            self.assertEqual(Config.load(path), config)
            self.assertEqual(config.obs_url, "tcp://192.0.2.20:26470?listen=1")

    def test_ssh_forward_uses_loopback_target(self):
        config = Config.from_mapping({**BASE, "sdb_ssh_host": "root@router.local"})
        self.assertEqual(config.sdb_target, "127.0.0.1:26101")
        with self.assertRaises(ConfigError):
            Config.from_mapping({**BASE, "sdb_ssh_host": "root@router.local",
                                 "sdb_target": "192.0.2.10:26101"})

    def test_sdb_network_serial_includes_port(self):
        config = Config.from_mapping({**BASE, "sdb_target": "display.local"})
        self.assertEqual(config.sdb_target, "display.local:26101")

    def test_invalid_capture_settings(self):
        for key, value in (("resolution", "3840x2160"), ("fps", 120),
                           ("audio_enabled", "false"),
                           ("audio_bitrate_kbps", 160), ("quality_mode", []),
                           ("control_port", 26470), ("control_port", 80)):
            with self.subTest(key=key), self.assertRaises(ConfigError):
                Config.from_mapping({**BASE, key: value})

    def test_high_mode_default_and_experimental_settings(self):
        config = Config.from_mapping({**BASE, "quality_mode": "high", "resolution": "1280x720", "fps": 30})
        self.assertEqual(config.video_bitrate_mbps, 12)
        self.assertEqual(config.dimensions, (1280, 720))

    def test_save_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("original")
            with self.assertRaises(ConfigError):
                Config.from_mapping(BASE).save(path)
            self.assertEqual(path.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
