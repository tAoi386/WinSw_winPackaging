"""
配置管理器 - 保存和加载WinSW路径等配置
"""
import os
import json
import tempfile
from typing import Optional


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self.config_dir = os.path.join(os.path.expanduser("~"), ".winsw-manager")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        return {key: value for key, value in loaded.items() if isinstance(value, str)}
            except:
                pass
        return {"winsw_path": "", "apps_dir": "", "jdk_path": ""}

    def _save_config(self):
        """保存配置"""
        os.makedirs(self.config_dir, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.config_dir, prefix=".config-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            os.replace(temporary, self.config_file)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    def get_winsw_path(self) -> str:
        """获取WinSW路径"""
        return self.config.get("winsw_path", "")

    def set_winsw_path(self, path: str):
        """设置WinSW路径"""
        self.update(winsw_path=path)

    def get_apps_dir(self) -> str:
        """获取应用目录"""
        return self.config.get("apps_dir", "")

    def set_apps_dir(self, path: str):
        """设置应用目录"""
        self.update(apps_dir=path)

    def get_jdk_path(self) -> str:
        """获取JDK路径"""
        return self.config.get("jdk_path", "")

    def set_jdk_path(self, path: str):
        """设置JDK路径"""
        self.update(jdk_path=path)

    def update(self, **values):
        """Commit all fields together and restore memory if persistence fails."""
        previous = self.config
        self.config = dict(previous, **values)
        try:
            self._save_config()
        except Exception:
            self.config = previous
            raise

    def is_winsw_configured(self) -> bool:
        """检查WinSW是否已配置"""
        path = self.get_winsw_path()
        if path and os.path.isfile(path):
            return True
        return False
