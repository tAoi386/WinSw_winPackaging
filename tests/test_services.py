import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import pywintypes

from core.service_manager import ServiceManager


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ServiceManager(self.tmp.name)
        self.states = {f"app{i}": 4 for i in range(5)}
        self.events = []
        for name in self.states:
            folder = Path(self.tmp.name, name)
            folder.mkdir()
            (folder / f"{name}.exe").write_bytes(b"test")
            (folder / "old app.jar").write_bytes(b"old")
            root = ET.Element("service")
            for tag, text in {"id": name, "name": name, "executable": "C:/custom/jdk/java.exe",
                              "arguments": '-Xms256m -Xmx2g -Dcustom=yes -jar "old app.jar" --spring.profiles.active=prod',
                              "logpath": "%BASE%/logs"}.items():
                ET.SubElement(root, tag).text = text
            ET.SubElement(root, "env", name="TOKEN", value="example")
            ET.ElementTree(root).write(folder / f"{name}.xml", encoding="utf-8")
        stack = self.enterContext(ExitStack())
        self.status = stack.enter_context(patch("core.service_manager.win32serviceutil.QueryServiceStatus", side_effect=self.query))
        self.start = stack.enter_context(patch("core.service_manager.win32serviceutil.StartService", side_effect=self.start_service))
        self.stop = stack.enter_context(patch("core.service_manager.win32serviceutil.StopService", side_effect=self.stop_service))
        self.delete = stack.enter_context(patch("core.service_manager.win32service.DeleteService", side_effect=self.delete_service))
        stack.enter_context(patch("core.service_manager.win32service.OpenSCManager", return_value="scm"))
        stack.enter_context(patch("core.service_manager.win32service.OpenService", side_effect=lambda scm, name, access: name))
        stack.enter_context(patch("core.service_manager.win32service.CloseServiceHandle"))
        self.config = stack.enter_context(patch("core.service_manager.win32service.QueryServiceConfig",
            side_effect=lambda name: (0, 0, 0, f'"{Path(self.tmp.name, name, name + ".exe")}"')))
        self.process = stack.enter_context(patch("core.service_manager.subprocess.run", side_effect=AssertionError("Unexpected process launch")))

    def query(self, name):
        if name not in self.states:
            raise pywintypes.error(1060, "QueryServiceStatus", "localized message")
        return (0, self.states[name], 0, 0, 0, 0, 0)

    def stop_service(self, name):
        self.events.append(("stop", name))
        self.states[name] = 1

    def start_service(self, name):
        self.events.append(("start", name))
        self.states[name] = 4

    def delete_service(self, name):
        self.events.append(("delete", name))
        del self.states[name]

    def test_delete_one_of_five_only_stops_target(self):
        result = self.manager.delete_service("app2")
        self.assertTrue(result["success"], result)
        self.assertEqual(self.events, [("stop", "app2"), ("delete", "app2")])
        self.assertEqual(self.states, {f"app{i}": 4 for i in (0, 1, 3, 4)})
        self.assertFalse(Path(self.tmp.name, "app2").exists())
        self.process.assert_not_called()

    def test_stop_timeout_blocks_delete_and_preserves_files(self):
        with patch.object(self.manager, "_wait_for", side_effect=TimeoutError("timeout")):
            result = self.manager.delete_service("app0")
        self.assertFalse(result["success"])
        self.delete.assert_not_called()
        self.assertTrue(Path(self.tmp.name, "app0", "old app.jar").exists())

    def test_delete_permission_failure_preserves_files(self):
        self.delete.side_effect = pywintypes.error(5, "DeleteService", "denied")
        self.assertFalse(self.manager.delete_service("app0")["success"])
        self.assertTrue(Path(self.tmp.name, "app0").exists())

    def test_missing_service_can_clean_local_deployment(self):
        del self.states["app0"]
        self.assertTrue(self.manager.delete_service("app0")["success"])
        self.stop.assert_not_called()

    def test_foreign_service_is_never_stopped(self):
        self.config.side_effect = None
        self.config.return_value = (0, 0, 0, '"C:/elsewhere/app0.exe"')
        self.assertFalse(self.manager.delete_service("app0")["success"])
        self.stop.assert_not_called()

    def test_service_id_cannot_escape_or_use_windows_reserved_names(self):
        for name in ("..", "../app0", "C:/outside", "CON", "LPT1.txt", "app0."):
            with self.subTest(name=name):
                self.assertFalse(self.manager.delete_service(name)["success"])
        self.stop.assert_not_called()

    def test_restart_waits_and_propagates_stop_failure(self):
        with patch.object(self.manager, "_wait_for", side_effect=TimeoutError("timeout")):
            self.assertFalse(self.manager.restart_service("app0")["success"])
        self.start.assert_not_called()

    def test_restart_stops_then_starts(self):
        self.assertTrue(self.manager.restart_service("app0")["success"])
        self.assertEqual(self.events, [("stop", "app0"), ("start", "app0")])

    def test_native_states_are_language_independent(self):
        names = ["Stopped", "StartPending", "StopPending", "Running", "ContinuePending", "PausePending", "Paused"]
        for code, name in enumerate(names, 1):
            self.states["app0"] = code
            self.assertEqual(self.manager.get_service_status("app0"), name)
        self.status.side_effect = pywintypes.error(5, "query", "拒绝访问")
        self.assertEqual(self.manager.get_service_status("app0"), "Access Denied")

    def test_start_waits_for_pending_to_finish(self):
        with patch.object(self.manager, "_assert_owned", return_value="Stopped"), \
             patch.object(self.manager, "get_service_status", side_effect=["StartPending", "Running"]), \
             patch("core.service_manager.time.sleep"):
            self.assertTrue(self.manager.start_service("app0")["success"])

    def test_start_failure_is_not_success(self):
        with patch.object(self.manager, "_assert_owned", return_value="Stopped"), \
             patch.object(self.manager, "get_service_status", return_value="Stopped"):
            self.assertFalse(self.manager.start_service("app0")["success"])

    def test_xml_upgrade_preserves_custom_configuration(self):
        path = Path(self.tmp.name, "app0", "app0.xml")
        before = ET.parse(path).getroot()
        self.assertTrue(self.manager.upgrade_service_xml("app0")["success"])
        after = ET.parse(path).getroot()
        for tag in ("executable", "arguments", "env"):
            self.assertEqual(ET.tostring(before.find(tag)), ET.tostring(after.find(tag)))
        self.assertTrue(Path(str(path) + ".bak").exists())

    def test_update_rejects_running_service(self):
        self.assertFalse(self.manager.update_jar("app0", str(Path(self.tmp.name, "app1", "old app.jar")))["success"])

    def test_update_handles_spaces_and_keeps_other_arguments(self):
        self.states["app0"] = 1
        source = Path(self.tmp.name, "new release.jar")
        source.write_bytes(b"new")
        result = self.manager.update_jar("app0", str(source))
        self.assertTrue(result["success"], result)
        args = ET.parse(Path(self.tmp.name, "app0", "app0.xml")).findtext("arguments")
        self.assertIn('-jar "new release.jar"', args)
        self.assertIn("--spring.profiles.active=prod", args)

    def test_failed_xml_write_rolls_back_jar(self):
        self.states["app0"] = 1
        source = Path(self.tmp.name, "old app.jar")
        source.write_bytes(b"new")
        with patch.object(self.manager, "_write_xml", side_effect=OSError("disk full")):
            self.assertFalse(self.manager.update_jar("app0", str(source))["success"])
        self.assertEqual(Path(self.tmp.name, "app0", "old app.jar").read_bytes(), b"old")

    def test_batch_stop_failure_skips_copy_and_start(self):
        source = str(Path(self.tmp.name, "app1", "old app.jar"))
        with patch.object(self.manager, "stop_service", return_value={"success": False, "message": "timeout"}), \
             patch.object(self.manager, "update_jar") as update:
            self.assertFalse(self.manager.deploy_jar("app0", source)["success"])
            update.assert_not_called()
        self.start.assert_not_called()

    def test_missing_source_does_not_stop_service(self):
        self.assertFalse(self.manager.deploy_jar("app0", "missing.jar")["success"])
        self.stop.assert_not_called()

    def test_duplicate_creation_does_not_overwrite_files(self):
        original = Path(self.tmp.name, "app0", "app0.xml").read_bytes()
        self.assertFalse(self.manager.create_service("app0", "changed", "missing.jar", "missing.exe")["success"])
        self.assertEqual(Path(self.tmp.name, "app0", "app0.xml").read_bytes(), original)

    def test_xml_escaping_and_quoted_jar(self):
        java = Path(self.tmp.name, "java.exe")
        java.write_bytes(b"test")
        xml = self.manager._generate_xml("new", "A & B <Service>", "some app.jar", 8080, "512m", self.tmp.name, self.tmp.name)
        root = ET.fromstring(xml)
        self.assertEqual(root.findtext("name"), "A & B <Service>")
        self.assertIn('-jar "some app.jar"', root.findtext("arguments"))
        self.assertEqual(root.findtext("log/sizeThreshold"), "102400")

    def test_invalid_update_plan_does_not_stop_service(self):
        source = str(Path(self.tmp.name, 'app0', 'old app.jar'))
        result = self.manager.deploy_jar('app0', source)
        self.assertFalse(result['success'])
        self.stop.assert_not_called()

    def test_missing_jar_argument_does_not_stop_service(self):
        xml = Path(self.tmp.name, 'app0', 'app0.xml')
        root = ET.parse(xml).getroot()
        root.find('arguments').text = '-version'
        ET.ElementTree(root).write(xml, encoding='utf-8')
        result = self.manager.deploy_jar('app0', str(Path(self.tmp.name, 'app1', 'old app.jar')))
        self.assertFalse(result['success'])
        self.stop.assert_not_called()

    def test_partial_directory_removal_keeps_retry_metadata(self):
        folder = Path(self.tmp.name, 'app0')
        def partial_removal(path):
            (Path(path) / 'app0.xml').unlink()
            raise PermissionError('jar still locked')
        with patch('core.service_manager.shutil.rmtree', side_effect=partial_removal):
            self.assertFalse(self.manager.delete_service('app0')['success'])
        self.assertTrue((folder / 'app0.xml').exists())
        self.assertTrue(self.manager.delete_service('app0')['success'])

    def test_directory_switch_failure_keeps_original_root(self):
        old = self.manager.apps_dir
        with patch('core.service_manager.os.makedirs', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.manager.set_apps_dir(str(Path(self.tmp.name, 'bad')))
        self.assertEqual(self.manager.apps_dir, old)


if __name__ == "__main__":
    unittest.main()
