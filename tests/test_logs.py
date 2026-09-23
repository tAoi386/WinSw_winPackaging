import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.service_manager import ServiceManager, tail_file
from core.log_reader import ConsoleReader


class LogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ServiceManager(self.tmp.name)
        self.folder = Path(self.tmp.name, "app")
        self.folder.mkdir()
        (self.folder / "app.xml").write_text('<service><id>app</id><logpath>%BASE%/logs</logpath></service>')
        self.logs = self.folder / "logs"
        self.logs.mkdir()
        self.out = self.logs / "app.out.log"
        self.err = self.logs / "app.err.log"

    def test_console_includes_stderr_and_entire_stack_not_wrapper(self):
        self.out.write_text("Started\n", encoding="utf-8")
        self.err.write_text("java.lang.Error\n    at Main.java:1\n  ... 22 more\nplain diagnostic\n", encoding="utf-8")
        (self.logs / "app.wrapper.log").write_text("WinSW starting")
        content = ConsoleReader(self.manager, "app").poll()
        self.assertIn("Started", content)
        self.assertIn("plain diagnostic", content)
        self.assertIn("... 22 more", content)
        self.assertNotIn("WinSW", content)

    def test_legacy_paths_and_rotated_names(self):
        (self.folder / "app.2.out.log").write_text("old\n")
        (self.folder / "winsw-stderr.log").write_text("legacy\n")
        self.out.write_text("new\n")
        content = ConsoleReader(self.manager, "app").poll()
        for word in ("old", "legacy", "new"):
            self.assertIn(word, content)

    def test_append_is_not_duplicated_and_preserves_partial_utf8(self):
        self.out.write_bytes(b"first\n")
        reader = ConsoleReader(self.manager, "app")
        self.assertEqual(reader.poll(), "first")
        data = "中文\n".encode()
        with self.out.open("ab") as stream:
            stream.write(data[:2])
        self.assertEqual(reader.poll(), "first")
        with self.out.open("ab") as stream:
            stream.write(data[2:])
        self.assertEqual(reader.poll(), "first\n中文")
        self.assertEqual(reader.poll(), "first\n中文")

    def test_partial_line_becomes_one_line(self):
        self.out.write_text("part")
        reader = ConsoleReader(self.manager, "app")
        self.assertEqual(reader.poll(), "part")
        with self.out.open("a") as stream:
            stream.write("ial\nnext\n")
        self.assertEqual(reader.poll(), "partial\nnext")

    def test_rotation_reads_unseen_old_tail_and_new_file(self):
        self.out.write_text("before\n")
        reader = ConsoleReader(self.manager, "app")
        reader.poll()
        with self.out.open("a") as stream:
            stream.write("last old\n")
        self.out.rename(self.logs / "app.1.out.log")
        self.out.write_text("after\n")
        self.assertEqual(reader.poll(), "before\nlast old\nafter")
        self.assertEqual(reader.poll(), "before\nlast old\nafter")

    def test_truncate_and_regrow_beyond_old_offset(self):
        self.out.write_text("old\n")
        reader = ConsoleReader(self.manager, "app")
        reader.poll()
        self.out.write_text("new much longer\n")
        self.assertEqual(reader.poll(), "old\nnew much longer")

    def test_global_line_limit(self):
        self.out.write_text("\n".join(str(i) for i in range(100)) + "\n")
        self.err.write_text("\n".join(str(i) for i in range(100, 200)) + "\n")
        os.utime(self.out, (10, 10))
        os.utime(self.err, (20, 20))
        lines = ConsoleReader(self.manager, "app", max_lines=10).poll().splitlines()
        self.assertEqual(lines, [str(i) for i in range(190, 200)])

    def test_tail_large_file_returns_last_lines(self):
        self.out.write_text("\n".join(f"line-{i}" for i in range(100000)))
        self.assertEqual(tail_file(str(self.out), 3), "line-99997\nline-99998\nline-99999")

    def test_clear_screen_does_not_delete_disk_history(self):
        self.out.write_text("old\n")
        reader = ConsoleReader(self.manager, "app")
        reader.poll()
        reader.clear()
        self.assertEqual(reader.poll(), "")
        self.assertEqual(self.out.read_text(), "old\n")

    def test_disk_clear_reports_permission_errors(self):
        self.out.write_text("old\n")
        with patch("builtins.open", side_effect=PermissionError("locked")):
            self.assertFalse(self.manager.clear_log("app")["success"])

    def test_custom_shared_log_dir_does_not_mix_other_services(self):
        (self.logs / "other.out.log").write_text("unrelated")
        self.out.write_text("ours")
        self.assertEqual(ConsoleReader(self.manager, "app").poll(), "ours")

    def test_similar_service_name_not_read_or_cleared(self):
        other = self.logs / 'app.worker.out.log'
        other.write_text('other service')
        self.out.write_text('ours')
        self.assertEqual(ConsoleReader(self.manager, 'app').poll(), 'ours')
        self.assertTrue(self.manager.clear_log('app')['success'])
        self.assertEqual(other.read_text(), 'other service')

    def test_clear_discards_unread_backlog(self):
        self.out.write_bytes(b'initial\n')
        reader = ConsoleReader(self.manager, 'app')
        reader.poll()
        with self.out.open('ab') as stream:
            stream.write(b'old backlog\n' * 200000)
        reader.clear()
        self.assertEqual(reader.poll(), '')
        with self.out.open('ab') as stream:
            stream.write(b'new output\n')
        self.assertEqual(reader.poll(), 'new output')


if __name__ == "__main__":
    unittest.main()
