"""Read-only validation of the one-file Windows release."""
import sys
from pathlib import Path
import pefile
from PyInstaller.archive.readers import CArchiveReader


def verify(path):
    path = Path(path)
    if sorted(p.name for p in path.parent.iterdir()) != [path.name]:
        raise RuntimeError("Release directory must contain only WinSw_winPackaging.exe")
    pe = pefile.PE(str(path))
    manifests = []
    try:
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == 24:
                for resource in entry.directory.entries:
                    for language in resource.directory.entries:
                        data = language.data.struct
                        manifests.append(pe.get_data(data.OffsetToData, data.Size).decode("utf-8"))
    finally:
        pe.close()
    if not any('level="requireAdministrator"' in manifest for manifest in manifests):
        raise RuntimeError("Administrator manifest missing")
    archive = CArchiveReader(str(path))
    if "main" not in archive.toc or "launcher" in archive.toc:
        raise RuntimeError("Expected direct main entry without a launcher")
    if not any(name.endswith("Qt5Core.dll") for name in archive.toc):
        raise RuntimeError("Embedded Qt runtime missing")
    print(f"Verified single EXE and administrator manifest: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    verify(sys.argv[1])
