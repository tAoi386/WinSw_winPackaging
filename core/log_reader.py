"""Bounded history and incremental console reading, including WinSW rotations."""
import codecs
import os
import re
from collections import deque

DEFAULT_LOG_LINES = 2000
MAX_LOG_LINES = 100000
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def log_kind(path):
    name = os.path.basename(path).lower()
    if re.search(r"(?:\.|-)(?:out|stdout)(?:\.\d+)?\.log(?:\.\d+)?$", name):
        return "out"
    if re.search(r"(?:\.|-)(?:err|stderr)(?:\.\d+)?\.log(?:\.\d+)?$", name):
        return "err"
    if ".wrapper" in name:
        return "wrapper"
    return None


def list_log_files(log_dir):
    if not log_dir or not os.path.isdir(log_dir):
        return []
    files = []
    for entry in os.scandir(log_dir):
        try:
            if entry.is_file(follow_symlinks=False) and log_kind(entry.name):
                files.append((entry.stat().st_mtime_ns, entry.path))
        except OSError:
            continue  # A rotation may remove a file during enumeration.
    return [p for _, p in sorted(files)]


def list_log_file_names(log_dir):
    return [os.path.basename(p) for p in list_log_files(log_dir)]


def tail_file(path, max_lines=DEFAULT_LOG_LINES, encoding="utf-8"):
    limit = max(1, min(int(max_lines or DEFAULT_LOG_LINES), MAX_LOG_LINES))
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            cursor = stream.tell()
            chunks, newlines, byte_count = [], 0, 0
            # Also bound pathological single-line files.
            while cursor and newlines <= limit and byte_count < 16 * 1024 * 1024:
                size = min(cursor, 8192)
                cursor -= size
                stream.seek(cursor)
                chunk = stream.read(size)
                chunks.append(chunk)
                newlines += chunk.count(b"\n")
                byte_count += len(chunk)
        return ANSI.sub("", b"".join(reversed(chunks)).decode(encoding, errors="replace")).splitlines()[-limit:]
    except FileNotFoundError:
        return []


class ConsoleReader:
    """Keep offsets by file identity so append/rename/truncate do not lose output.

    Separate stdout/stderr files contain no shared ordering information. History
    follows file modification order; live output follows observation order.
    """
    def __init__(self, manager, service, channel="console", max_lines=DEFAULT_LOG_LINES, encoding="utf-8"):
        self.manager, self.service, self.channel = manager, service, channel
        self.max_lines = max(1, min(int(max_lines), MAX_LOG_LINES))
        self.encoding = encoding
        self.lines = deque(maxlen=self.max_lines)
        self.states = {}
        self.initialized = False

    def _paths(self):
        return [p for p in self.manager._list_log_paths(self.service)
                if log_kind(p) in ({"out", "err"} if self.channel == "console" else {self.channel})]

    @staticmethod
    def _identity(st):
        return st.st_dev, st.st_ino

    def _state(self, stream):
        offset = stream.tell()
        stream.seek(max(0, offset - 64))
        anchor = stream.read(offset - stream.tell())
        stream.seek(offset)
        return {"offset": offset, "anchor": anchor,
                "decoder": codecs.getincrementaldecoder(self.encoding)(errors="replace"), "partial": ""}

    def _seed(self, paths):
        # Capture offsets before reading history, so concurrent appends aren't skipped.
        snapshots = []
        for path in paths:
            try:
                with open(path, "rb") as stream:
                    st = os.fstat(stream.fileno())
                    stream.seek(0, os.SEEK_END)
                    state = self._state(stream)
                    self.states[self._identity(st)] = state
                    snapshots.append((path, state["offset"]))
            except FileNotFoundError:
                continue
        remaining = self.max_lines
        blocks = []
        for path, end in reversed(snapshots):
            if remaining <= 0:
                break
            try:
                with open(path, "rb") as stream:
                    cursor, chunks, count, size = end, [], 0, 0
                    while cursor and count <= remaining and size < 16 * 1024 * 1024:
                        length = min(8192, cursor)
                        cursor -= length
                        stream.seek(cursor)
                        chunk = stream.read(length)
                        chunks.append(chunk)
                        count += chunk.count(b"\n")
                        size += len(chunk)
                    data = b"".join(reversed(chunks))
                    state = self.states.get(self._identity(os.fstat(stream.fileno())))
                    if state is None:
                        continue
                    text = state["decoder"].decode(data)
                    parts = ANSI.sub("", text).replace("\r\n", "\n").split("\n")
                    state["partial"] = parts.pop()
                    lines = parts[-remaining:]
                    blocks.append(lines)
                    remaining -= len(lines)
            except FileNotFoundError:
                continue
        for block in reversed(blocks):
            self.lines.extend(block)

    def poll(self):
        paths = self._paths()
        if not self.initialized:
            self._seed(paths)
            self.initialized = True
        seen = set()
        for path in paths:
            try:
                with open(path, "rb") as stream:
                    st = os.fstat(stream.fileno())
                    key = self._identity(st)
                    seen.add(key)
                    state = self.states.get(key)
                    if state:
                        stream.seek(max(0, state["offset"] - len(state["anchor"])))
                        changed = stream.read(len(state["anchor"])) != state["anchor"]
                    else:
                        changed = False
                    if state is None or st.st_size < state["offset"] or changed:
                        stream.seek(0)
                        state = self._state(stream)
                        self.states[key] = state
                    stream.seek(state["offset"])
                    data = stream.read(1024 * 1024)  # Catch up over ticks without freezing Qt.
                    if not data:
                        continue
                    decoded = state["partial"] + state["decoder"].decode(data)
                    parts = ANSI.sub("", decoded).replace("\r\n", "\n").split("\n")
                    state["partial"] = parts.pop()[-1024 * 1024:]
                    self.lines.extend(parts)
                    state["offset"] = stream.tell()
                    stream.seek(max(0, state["offset"] - 64))
                    state["anchor"] = stream.read(state["offset"] - stream.tell())
            except FileNotFoundError:
                continue
        for key in set(self.states) - seen:
            partial = self.states.pop(key)["partial"]
            if partial:
                self.lines.append(partial)
        partials = [s["partial"] for s in self.states.values() if s["partial"]]
        return "\n".join((list(self.lines) + partials)[-self.max_lines:])

    def clear(self):
        # Skip all bytes already on disk, including backlog larger than one poll.
        states = {}
        for path in self._paths():
            try:
                with open(path, "rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    states[self._identity(os.fstat(stream.fileno()))] = self._state(stream)
            except FileNotFoundError:
                continue
        self.states = states
        self.initialized = True
        self.lines.clear()
