"""WinSW operations with ownership checks and verified state transitions."""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from functools import wraps

import win32service
import win32serviceutil
import win32con
from core.log_reader import (ConsoleReader, DEFAULT_LOG_LINES, MAX_LOG_LINES,
                             list_log_files, list_log_file_names, tail_file as _tail_lines)

LOG_SUBDIR = "logs"
STATE_NAMES = {1: "Stopped", 2: "StartPending", 3: "StopPending", 4: "Running",
               5: "ContinuePending", 6: "PausePending", 7: "Paused"}
PENDING = {"StartPending", "StopPending", "ContinuePending", "PausePending"}
JAR_ARGUMENT = re.compile(r'(?<!\S)-jar\s+(?:"([^"]+)"|(\S+))')


def tail_file(path, max_lines=DEFAULT_LOG_LINES, encoding="utf-8"):
    try:
        return "\n".join(_tail_lines(path, max_lines, encoding))
    except OSError as exc:
        return f"[读取失败] {exc}"


read_file = tail_file


def filter_lines(text, keyword):
    keyword = keyword.strip().casefold()
    return "\n".join(line for line in text.splitlines() if keyword in line.casefold()) if keyword else text


def operation(method):
    @wraps(method)
    def guarded(self, service_name, *args, **kwargs):
        try:
            self._service_path(service_name)
            with self._locks_guard:
                lock = self._locks.setdefault(service_name.casefold(), threading.RLock())
            if not lock.acquire(blocking=False):
                return {"success": False, "message": "该服务正在执行其他操作，请稍后重试"}
            try:
                return method(self, service_name, *args, **kwargs)
            finally:
                lock.release()
        except Exception as exc:
            return {"success": False, "message": str(exc)}
    return guarded


class ServiceInfo:
    def __init__(self, name, display_name, status, exe_path=""):
        self.name, self.display_name, self.status, self.exe_path = name, display_name, status, exe_path


class ServiceManager:
    def __init__(self, apps_dir=None, config_manager=None):
        self.config_manager = config_manager
        self._locks, self._locks_guard = {}, threading.Lock()
        self.set_apps_dir(apps_dir or os.path.join(os.path.expanduser("~"), ".winsw-manager", "apps"))

    def set_apps_dir(self, new_dir):
        new_dir = os.path.abspath(new_dir)
        os.makedirs(new_dir, exist_ok=True)
        self.apps_dir = new_dir

    def _service_path(self, name):
        reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
        if (not isinstance(name, str) or not re.fullmatch(r"[\w-][\w.-]{0,127}", name)
                or name.endswith(".") or name.split(".")[0].upper() in reserved):
            raise ValueError("服务ID只能含字母、数字、中文、下划线、连字符和点，不能使用 Windows 保留名称")
        root = os.path.normcase(os.path.realpath(self.apps_dir))
        path = os.path.abspath(os.path.join(self.apps_dir, name))
        resolved = os.path.normcase(os.path.realpath(path))
        if resolved == root or os.path.commonpath([root, resolved]) != root:
            raise ValueError("服务目录不在应用根目录内，拒绝操作")
        if os.path.islink(path) or (hasattr(os.path, "isjunction") and os.path.isjunction(path)):
            raise ValueError("服务目录不能是符号链接或目录联接")
        return path

    @contextmanager
    def _handle(self, name, access):
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        handle = None
        try:
            handle = win32service.OpenService(scm, name, access)
            yield handle
        finally:
            if handle is not None:
                win32service.CloseServiceHandle(handle)
            win32service.CloseServiceHandle(scm)

    def get_service_status(self, service_name):
        try:
            code = win32serviceutil.QueryServiceStatus(service_name)[1]
            return STATE_NAMES.get(code, f"Unknown({code})")
        except Exception as exc:
            code = getattr(exc, "winerror", exc.args[0] if exc.args else None)
            return {1060: "Not Found", 5: "Access Denied", 1072: "DeletePending"}.get(code, "Unknown")

    def _assert_owned(self, name):
        folder = self._service_path(name)
        root = ET.parse(os.path.join(folder, f"{name}.xml")).getroot()
        if (root.findtext("id") or "").casefold() != name.casefold():
            raise ValueError("服务ID与XML不一致，拒绝操作")
        status = self.get_service_status(name)
        if status == "Not Found":
            return status
        if status in ("Unknown", "Access Denied", "DeletePending"):
            raise RuntimeError(f"无法安全操作服务，当前状态: {status}")
        with self._handle(name, win32service.SERVICE_QUERY_CONFIG) as handle:
            binary = win32service.QueryServiceConfig(handle)[3].strip()
        match = re.match(r'^"([^"]+)"|^(.+?\.exe)(?:\s|$)', binary, re.I)
        executable = next((v for v in match.groups() if v), "") if match else binary
        expected = os.path.join(folder, f"{name}.exe")
        if os.path.normcase(os.path.realpath(os.path.expandvars(executable))) != os.path.normcase(os.path.realpath(expected)):
            raise ValueError("Windows 中的同名服务不属于此目录，拒绝操作")
        return status

    def _wait_for(self, name, target, timeout=60):
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_service_status(name)
            if status == target:
                return
            if status not in PENDING and not (target == "Not Found" and status in {"Stopped", "DeletePending"}):
                raise RuntimeError(f"服务 {name} 未达到 {target}，当前状态: {status}；请查看控制台及 WinSW 日志")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待服务 {name} 变为 {target} 超时，当前状态: {status}；操作未完成")
            time.sleep(0.25)

    @operation
    def start_service(self, service_name):
        status = self._assert_owned(service_name)
        if status == "Running":
            return {"success": True, "message": f"服务 {service_name} 已在运行"}
        if status == "StopPending":
            self._wait_for(service_name, "Stopped")
            status = "Stopped"
        if status == "Stopped":
            win32serviceutil.StartService(service_name)
        elif status != "StartPending":
            raise RuntimeError(f"无法启动，当前状态: {status}")
        self._wait_for(service_name, "Running")
        return {"success": True, "message": f"服务 {service_name} 已运行（应用就绪请查看启动日志）"}

    @operation
    def stop_service(self, service_name, wait_for_stop=True):
        status = self._assert_owned(service_name)
        if status in {"Stopped", "Not Found"}:
            return {"success": True, "message": f"服务 {service_name} 已停止"}
        if status in {"StartPending", "ContinuePending"}:
            self._wait_for(service_name, "Running")
        elif status == "PausePending":
            self._wait_for(service_name, "Paused")
        if status != "StopPending":
            win32serviceutil.StopService(service_name)
        if wait_for_stop:
            self._wait_for(service_name, "Stopped")
        return {"success": True, "message": f"服务 {service_name} " + ("已停止" if wait_for_stop else "已收到停止请求")}

    @operation
    def restart_service(self, service_name):
        stopped = self.stop_service(service_name)
        return self.start_service(service_name) if stopped["success"] else stopped

    @operation
    def delete_service(self, service_name):
        # WinSW stops its own process tree; never kill by image name.
        status = self._assert_owned(service_name)
        if status != "Not Found":
            stopped = self.stop_service(service_name)
            if not stopped["success"]:
                return stopped
            with self._handle(service_name, win32con.DELETE) as handle:
                win32service.DeleteService(handle)
            self._wait_for(service_name, "Not Found", timeout=30)
        folder = self._service_path(service_name)  # Revalidate before recursive removal.
        xml_path = os.path.join(folder, f"{service_name}.xml")
        recovery_xml = ET.parse(xml_path).getroot()
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            # rmtree may already have removed the XML before hitting a locked JAR.
            # Keep the deployment discoverable so the user can retry cleanup.
            if os.path.isdir(folder) and not os.path.exists(xml_path):
                try:
                    self._write_xml(xml_path, recovery_xml)
                except OSError as restore_error:
                    return {"success": False, "message": f"服务已卸载，目录清理失败: {exc}；恢复清理标记失败: {restore_error}。请手动检查 {folder}"}
            return {"success": False, "message": f"服务已卸载，但目录清理失败，可重试删除: {exc}"}
        return {"success": True, "message": f"服务 {service_name} 已停止、卸载并清理目录"}

    def _find_java_exe(self):
        configured = self.config_manager.get_jdk_path() if self.config_manager else ""
        if configured:
            java = os.path.join(configured, "java.exe")
            if not os.path.isfile(java):
                raise ValueError("配置的 JDK 路径无效")
            return java
        home = os.environ.get("JAVA_HOME", "")
        java = os.path.join(home, "bin", "java.exe") if home else ""
        java = java if os.path.isfile(java) else shutil.which("java")
        if not java:
            raise ValueError("未找到 Java，请先配置 JDK bin 目录")
        return java

    def _generate_xml(self, service_name, display_name, jar_file, port, jvm_memory, working_dir, jdk_bin=""):
        java = os.path.join(jdk_bin, "java.exe") if jdk_bin else self._find_java_exe()
        if not os.path.isfile(java):
            raise ValueError("JDK bin 目录中不存在 java.exe")
        if not re.fullmatch(r"[1-9]\d*[mMgG]", jvm_memory) or not 1 <= int(port) <= 65535:
            raise ValueError("JVM内存或端口无效")
        root = ET.Element("service")
        for tag, value in {
            "id": service_name, "name": display_name, "description": f"{display_name} Windows Service",
            "executable": java,
            "arguments": f'-Xms{jvm_memory} -Xmx{jvm_memory} -Dfile.encoding=UTF-8 -jar "{jar_file}" --server.port={port}',
            "workingdirectory": working_dir, "logpath": os.path.join(working_dir, LOG_SUBDIR),
        }.items():
            ET.SubElement(root, tag).text = value
        log = ET.SubElement(root, "log", mode="roll-by-size")
        ET.SubElement(log, "sizeThreshold").text = "102400"  # KB: 100 MB.
        ET.SubElement(log, "keepFiles").text = "8"
        ET.SubElement(root, "stopparentprocessfirst").text = "true"
        return ET.tostring(root, encoding="unicode")

    @staticmethod
    def _write_xml(path, root):
        fd, temporary = tempfile.mkstemp(prefix=".xml-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as stream:
                ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    @operation
    def create_service(self, service_name, display_name, jar_path, winsw_exe_path, port=8080, jvm_memory="512m", jdk_bin=""):
        folder = self._service_path(service_name)
        if os.path.exists(folder) or self.get_service_status(service_name) != "Not Found":
            raise ValueError("服务ID或目录已存在（或无权查询），请使用新的服务ID")
        self._validate_jar(jar_path)
        if not winsw_exe_path or not os.path.isfile(winsw_exe_path):
            raise ValueError("WinSW 可执行文件不存在")
        xml = self._generate_xml(service_name, display_name, os.path.basename(jar_path), port, jvm_memory, folder, jdk_bin)
        os.makedirs(folder)
        shutil.copy2(jar_path, folder)
        exe = os.path.join(folder, f"{service_name}.exe")
        shutil.copy2(winsw_exe_path, exe)
        self._write_xml(os.path.join(folder, f"{service_name}.xml"), ET.fromstring(xml))
        proc = subprocess.run([exe, "install"], cwd=folder, capture_output=True, text=True,
                              errors="replace", timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        if proc.returncode or self.get_service_status(service_name) == "Not Found":
            raise RuntimeError(f"安装失败，目录已保留供检查: {proc.stderr.strip() or proc.stdout.strip()}")
        self._assert_owned(service_name)
        return {"success": True, "message": f"服务 {display_name} 创建成功", "path": folder}

    def get_all_services(self):
        services = []
        if not os.path.exists(self.apps_dir):
            return services
        for name in sorted(os.listdir(self.apps_dir), key=str.casefold):
            try:
                folder = self._service_path(name)
                root = ET.parse(os.path.join(folder, f"{name}.xml")).getroot()
                if (root.findtext("id") or "").casefold() != name.casefold():
                    continue
                services.append(ServiceInfo(name, root.findtext("name") or name, self.get_service_status(name), folder))
            except (OSError, ValueError, ET.ParseError):
                continue
        return services

    def get_service_dir(self, service_name):
        folder = self._service_path(service_name)
        return folder if os.path.isdir(folder) else None

    def get_apps_dir(self):
        return self.apps_dir

    @staticmethod
    def _validate_jar(path):
        if not os.path.isfile(path) or not path.lower().endswith(".jar"):
            raise ValueError(f"JAR文件不存在或扩展名无效: {path}")

    def _prepare_jar_update(self, service_name, new_jar_path):
        """Validate paths and XML before an update is allowed to stop the service."""
        self._validate_jar(new_jar_path)
        folder = self._service_path(service_name)
        xml_path = os.path.join(folder, f"{service_name}.xml")
        root = ET.parse(xml_path).getroot()
        args = root.find("arguments")
        if args is None or not JAR_ARGUMENT.search(args.text or ""):
            raise ValueError("XML中缺少有效的 -jar 参数，未修改任何文件")
        filename = os.path.basename(new_jar_path)
        dest = os.path.join(folder, filename)
        if os.path.normcase(os.path.realpath(new_jar_path)) == os.path.normcase(os.path.realpath(dest)):
            raise ValueError("请选择部署目录以外的新版 JAR")
        if os.path.islink(dest):
            raise ValueError("目标 JAR 不能是符号链接")
        args.text = JAR_ARGUMENT.sub(lambda _: '-jar "' + filename + '"', args.text, count=1)
        return folder, xml_path, root, filename, dest

    @operation
    def update_jar(self, service_name, new_jar_path):
        folder, xml_path, root, filename, dest = self._prepare_jar_update(service_name, new_jar_path)
        if self._assert_owned(service_name) not in {"Stopped", "Not Found"}:
            raise RuntimeError("服务尚未停止，拒绝覆盖 JAR")
        fd, stage = tempfile.mkstemp(prefix=".jar-", dir=folder)
        os.close(fd)
        existed, replaced = os.path.exists(dest), False
        backup = dest + ".bak"
        try:
            shutil.copy2(new_jar_path, stage)
            shutil.copy2(xml_path, xml_path + ".bak")
            if existed:
                shutil.copy2(dest, backup)
            os.replace(stage, dest)
            replaced = True
            self._write_xml(xml_path, root)
        except Exception:
            if replaced:
                if existed:
                    os.replace(backup, dest)
                else:
                    os.remove(dest)
            raise
        finally:
            if os.path.exists(stage):
                os.remove(stage)
        return {"success": True, "message": f"JAR已更新: {filename}（原配置已备份）"}

    @operation
    def deploy_jar(self, service_name, jar_path, stop_before=True, start_after=True):
        self._prepare_jar_update(service_name, jar_path)
        if stop_before:
            result = self.stop_service(service_name)
            if not result["success"]:
                return result
        result = self.update_jar(service_name, jar_path)
        if not result["success"]:
            return result
        if start_after:
            started = self.start_service(service_name)
            if not started["success"]:
                return {"success": False, "message": f"JAR已更新，但启动失败: {started['message']}"}
        return {"success": True, "message": "更新完成" + ("，服务已运行" if start_after else "，服务保持停止")}

    @operation
    def upgrade_service_xml(self, service_name, restart=True):
        status = self._assert_owned(service_name)
        if status in PENDING:
            raise RuntimeError("服务正在切换状态，请稍后更新配置")
        folder = self._service_path(service_name)
        path = os.path.join(folder, f"{service_name}.xml")
        root = ET.parse(path).getroot()
        # Patch logging only: preserve JDK, arguments, environment and dependencies.
        logpath = root.find("logpath")
        if logpath is None:
            logpath = ET.SubElement(root, "logpath")
            logpath.text = os.path.join(folder, LOG_SUBDIR)
        log = root.find("log")
        if log is None:
            log = ET.SubElement(root, "log", mode="roll-by-size")
        if log.get("mode") == "roll-by-size":
            size = log.find("sizeThreshold")
            if size is None:
                size = ET.SubElement(log, "sizeThreshold")
            if not size.text or size.text.strip() == "104857600":
                size.text = "102400"
            if log.find("keepFiles") is None:
                ET.SubElement(log, "keepFiles").text = "8"
        shutil.copy2(path, path + ".bak")
        was_running = status == "Running"
        if restart and was_running:
            stopped = self.stop_service(service_name)
            if not stopped["success"]:
                return stopped
        self._write_xml(path, root)
        if restart and was_running:
            started = self.start_service(service_name)
            if not started["success"]:
                return {"success": False, "message": f"配置已更新，但重启失败: {started['message']}"}
        return {"success": True, "message": "日志配置已更新，原有 JDK、参数及自定义配置均已保留；原 XML 已备份",
                "restarted": restart and was_running}

    def get_log_dir(self, service_name):
        folder = self.get_service_dir(service_name)
        if not folder:
            return None
        root = ET.parse(os.path.join(folder, f"{service_name}.xml")).getroot()
        configured = root.findtext("logpath")
        if configured:
            value = re.sub(r"%BASE%", lambda _: folder, configured.strip(), flags=re.I)
            value = os.path.expandvars(value)
            return os.path.abspath(value if os.path.isabs(value) else os.path.join(folder, value))
        return folder

    def _list_log_paths(self, service_name):
        folder = self.get_service_dir(service_name)
        if not folder:
            return []
        dirs = {self.get_log_dir(service_name), folder, os.path.join(folder, LOG_SUBDIR)}
        paths = {p for d in dirs if d for p in list_log_files(d)}
        root = ET.parse(os.path.join(folder, f"{service_name}.xml")).getroot()
        prefixes = {service_name.casefold(), (root.findtext("logname") or service_name).casefold()}
        own_dirs = {os.path.normcase(os.path.realpath(folder)), os.path.normcase(os.path.realpath(os.path.join(folder, LOG_SUBDIR)))}
        result = []
        for path in paths:
            name = os.path.basename(path).casefold()
            local = os.path.normcase(os.path.realpath(os.path.dirname(path))) in own_dirs
            # A simple startswith("app.") also matches app.worker.out.log.
            suffix = r"(?:[0-9][0-9T._-]*\.)?(?:out|err|stdout|stderr|wrapper)(?:\.\d+)?\.log(?:\.\d+)?"
            owned = any(re.fullmatch(re.escape(p) + r"\." + suffix, name) for p in prefixes)
            legacy = local and re.fullmatch(r"winsw[.-]" + suffix, name)
            if owned or legacy:
                try:
                    result.append((os.path.getmtime(path), path))
                except FileNotFoundError:
                    pass
        return [p for _, p in sorted(result)]

    def list_log_files(self, service_name):
        return [os.path.basename(p) for p in self._list_log_paths(service_name)]

    def tail_combined_logs(self, service_name, max_lines=DEFAULT_LOG_LINES, show_errors_only=False):
        return ConsoleReader(self, service_name, "err" if show_errors_only else "console", max_lines).poll()

    def tail_all_logs(self, service_name, max_lines=DEFAULT_LOG_LINES):
        return self.tail_combined_logs(service_name, max_lines)

    def tail_log(self, service_name, log_file="", max_lines=DEFAULT_LOG_LINES):
        paths = self._list_log_paths(service_name)
        path = next((p for p in paths if os.path.basename(p) == log_file), paths[-1] if paths else None)
        return tail_file(path, max_lines) if path else ""

    def get_logs(self, service_name, log_type="all"):
        return self.tail_all_logs(service_name)

    def get_err_logs(self, service_name):
        return self.tail_combined_logs(service_name, show_errors_only=True)

    @operation
    def clear_log(self, service_name):
        failures, count = [], 0
        for path in self._list_log_paths(service_name):
            try:
                with open(path, "r+b") as stream:
                    stream.truncate(0)
                count += 1
            except OSError as exc:
                failures.append(f"{os.path.basename(path)}: {exc}")
        return {"success": not failures, "message": f"已清空 {count} 个日志文件" + ("；失败: " + "；".join(failures) if failures else "")}
