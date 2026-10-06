"""Zip the release folder (python tools/zip_release.py SRC_DIR OUT_ZIP).

Unlike Compress-Archive, this opens files with shared read access and retries
briefly, so a sync client (e.g. OneDrive) scanning fresh files doesn't break it.
"""
import sys
import time
import zipfile
from pathlib import Path


def add(archive, path, name, attempts=10):
    for attempt in range(attempts):
        try:
            archive.write(path, name)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def main(src, out):
    src, out = Path(src), Path(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                add(archive, path, Path(src.name) / path.relative_to(src))
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
