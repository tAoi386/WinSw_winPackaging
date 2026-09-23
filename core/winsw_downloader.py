"""Download the executable actually published in the GitHub release assets."""
import os
import platform
import tempfile
import requests


class WinSWDownloader:
    GITHUB_API_URL = "https://api.github.com/repos/winsw/winsw/releases/latest"

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".winsw-manager", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._release = None

    def _get_release(self):
        if self._release is None:
            response = requests.get(self.GITHUB_API_URL, timeout=20)
            response.raise_for_status()
            release = response.json()
            if not release.get("tag_name") or not isinstance(release.get("assets"), list):
                raise RuntimeError("GitHub 未返回有效的 WinSW 发布信息")
            self._release = release
        return self._release

    def get_latest_version(self):
        return self._get_release()["tag_name"].lstrip("v")

    def get_download_url(self):
        # A 32-bit Python interpreter can run on 64-bit Windows.
        arch = os.environ.get("PROCESSOR_ARCHITEW6432", platform.machine()).lower()
        filename = "WinSW-x64.exe" if arch in {"amd64", "x86_64", "arm64", "aarch64"} else "WinSW-x86.exe"
        asset = next((a for a in self._get_release()["assets"] if a.get("name", "").lower() == filename.lower()), None)
        if not asset:
            raise RuntimeError(f"当前 WinSW 发布中未找到 {filename}，请手动选择兼容的可执行文件")
        return asset["browser_download_url"], asset["name"]

    @staticmethod
    def _is_executable(path):
        try:
            with open(path, "rb") as stream:
                return stream.read(2) == b"MZ"
        except OSError:
            return False

    def download(self, progress_callback=None):
        url, filename = self.get_download_url()
        version = self.get_latest_version()
        if os.path.basename(version) != version or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-_" for c in version):
            raise ValueError("发布版本号无效")
        folder = os.path.join(self.cache_dir, version)
        os.makedirs(folder, exist_ok=True)
        destination = os.path.join(folder, filename)
        if self._is_executable(destination):
            return destination
        fd, temporary = tempfile.mkstemp(dir=folder, suffix=".download")
        try:
            with os.fdopen(fd, "wb") as stream, requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total, received = int(response.headers.get("content-length", 0)), 0
                for chunk in response.iter_content(65536):
                    if chunk:
                        stream.write(chunk)
                        received += len(chunk)
                        if progress_callback and total:
                            progress_callback(min(100, received * 100 // total))
                if total and received != total:
                    raise RuntimeError("WinSW 下载不完整，请重试")
            if not self._is_executable(temporary):
                raise RuntimeError("下载内容不是 Windows 可执行文件")
            os.replace(temporary, destination)
            return destination
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def get_local_exe_path(self):
        for folder, _, names in os.walk(self.cache_dir):
            for name in names:
                path = os.path.join(folder, name)
                if name.lower().startswith("winsw") and name.lower().endswith(".exe") and self._is_executable(path):
                    return path
        return None
