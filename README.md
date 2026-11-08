# WhatsApp Cache Cleaner

**Author:** ELANGOVAN  
**NVDA add-on version:** 1.10

WhatsApp Cache Cleaner is an NVDA add-on for Windows. It provides a keyboard-accessible workflow to inspect recognised WhatsApp cache folders, check for related running processes, and clean recognised cache folders after confirmation.

## Main functions

1. **Scan storage** — measures the recognised WhatsApp cache folders.
2. **Check processes** — checks `WhatsApp.exe` and WebView2 process command/path and parent-process information before enabling cleanup.
3. **Clean cache** — becomes available only after a successful scan and process check, and asks for separate confirmation.

## Important safety information

- The add-on does not force-close applications.
- It does not bypass Windows permissions, take ownership, or elevate privileges.
- It limits cleanup to the recognised cache folders listed in the source code.
- It protects LocalState, session databases, IndexedDB, cookies, Local Storage, account/session data, and unlisted folders.
- If a relevant WebView2 process cannot be identified with sufficient confidence, cleanup remains disabled.
- Some cached application resources or media may need to be downloaded again after cleanup.
- This project has not been independently security-audited. Review the source before using it, and keep a backup of important data.

## Install

Download the `.nvda-addon` file from the GitHub Releases page. Open the downloaded installer and follow NVDA's add-on installation prompt. Restart NVDA when requested.

## Build from source

Requirements: Python 3.

```powershell
python build_addon.py
```

The script creates `dist/WhatsApp-Cache-Cleaner-1.10.nvda-addon`.

## Project contents

- `manifest.ini` — NVDA add-on metadata.
- `globalPlugins/whatsappCacheCleaner.py` — add-on source code.
- `readme.html` — help text shown by NVDA.
- `build_addon.py` — creates the installable NVDA add-on archive.

## Compatibility

The manifest currently declares NVDA 2022.1 as the minimum version and NVDA 2025.3.1 as the last tested version. Compatibility with other NVDA versions should be verified before publishing a new release.
