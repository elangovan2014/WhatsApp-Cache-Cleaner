#!/usr/bin/env python3
"""Build the WhatsApp Cache Cleaner NVDA add-on package."""
from pathlib import Path
import configparser
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.ini"
REQUIRED = [MANIFEST, ROOT / "readme.html", ROOT / "globalPlugins" / "whatsappCacheCleaner.py"]


def main() -> int:
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    if missing:
        print("Missing required files: " + ", ".join(missing), file=sys.stderr)
        return 1

    parser = configparser.ConfigParser()
    try:
        parser.read(MANIFEST, encoding="utf-8")
        version = parser.get("addon", "version", fallback=None)
    except configparser.Error:
        # NVDA manifest.ini uses key/value lines without a section header.
        version = None
    if version is None:
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version") and "=" in line:
                version = line.split("=", 1)[1].strip().strip('"')
                break
    if not version:
        print("Could not read add-on version from manifest.ini", file=sys.stderr)
        return 1

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    output = dist / f"WhatsApp-Cache-Cleaner-{version}.nvda-addon"
    files = [ROOT / "manifest.ini", ROOT / "readme.html", ROOT / "globalPlugins" / "whatsappCacheCleaner.py"]
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(output, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise zipfile.BadZipFile(f"CRC check failed for {bad}")
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1

    print(f"Created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
