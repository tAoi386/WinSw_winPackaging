import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from core.config_manager import ConfigManager
from core.winsw_downloader import WinSWDownloader


class ConfigDownloadTests(unittest.TestCase):
    def test_malformed_config_is_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, ".winsw-manager")
            path.mkdir()
            (path / "config.json").write_text('["invalid"]')
            with patch("core.config_manager.os.path.expanduser", return_value=folder):
                config = ConfigManager()
                self.assertEqual(config.get_apps_dir(), "")
                config.set_apps_dir("C:/apps")
                self.assertEqual(ConfigManager().get_apps_dir(), "C:/apps")

    def test_download_uses_release_asset_not_invented_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            downloader = WinSWDownloader(folder)
            downloader._release = {"tag_name": "v2.12.0", "assets": [
                {"name": "WinSW-x64.exe", "browser_download_url": "https://github.com/example/WinSW-x64.exe"}]}
            with patch.dict("os.environ", {"PROCESSOR_ARCHITEW6432": "AMD64"}):
                url, name = downloader.get_download_url()
                self.assertEqual(name, "WinSW-x64.exe")
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.headers = {"content-length": "6"}
                response.iter_content.return_value = [b"MZtest"]
                with patch("core.winsw_downloader.requests.get", return_value=response):
                    path = downloader.download()
            self.assertEqual(Path(path).read_bytes(), b"MZtest")
            self.assertIn("2.12.0", path)

    def test_network_failure_does_not_fabricate_version(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("core.winsw_downloader.requests.get", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    WinSWDownloader(folder).get_latest_version()

    def test_failed_save_preserves_memory_and_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('core.config_manager.os.path.expanduser', return_value=folder):
                config = ConfigManager()
                config.set_apps_dir('original')
                with patch('core.config_manager.os.replace', side_effect=PermissionError('denied')):
                    with self.assertRaises(PermissionError):
                        config.update(apps_dir='changed', jdk_path='changed')
                self.assertEqual(config.get_apps_dir(), 'original')
                self.assertEqual(ConfigManager().get_apps_dir(), 'original')


if __name__ == "__main__":
    unittest.main()
