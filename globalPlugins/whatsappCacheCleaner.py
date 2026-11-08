# -*- coding: UTF-8 -*-
# WhatsApp Cache Cleaner 1.10
# Separate scan, process check, and confirmed cleanup.
import os
import json
import shutil
import subprocess
import threading
import wx
import gui
import ui
import globalPluginHandler
from scriptHandler import script

CACHE_RELATIVE = [
    ("Default\\Cache", "Browser Cache"),
    ("Default\\Code Cache", "Code Cache"),
    ("Default\\GPUCache", "GPU Cache"),
    ("Default\\GrShaderCache", "Graphics Shader Cache"),
    ("Default\\ShaderCache", "Shader Cache"),
    ("Default\\DawnGraphiteCache", "Dawn Graphite Cache"),
    ("Default\\DawnWebGPUCache", "Dawn WebGPU Cache"),
    ("Default\\Service Worker\\ScriptCache", "Service Worker Script Cache"),
    ("Default\\Service Worker\\CacheStorage", "Service Worker CacheStorage"),
]
PROTECTED = ("LocalState, session databases, IndexedDB, cookies, Local Storage, "
             "account/session data, and all unlisted folders")

def fmt(n):
    if n >= 1024 ** 2:
        return "%.2f MB" % (n / float(1024 ** 2))
    if n >= 1024:
        return "%.2f KB" % (n / 1024.0)
    return "%d bytes" % n

def folder_size(path):
    total = 0
    if not os.path.isdir(path):
        return 0
    for current, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(current, d))]
        for name in files:
            full = os.path.join(current, name)
            try:
                if not os.path.islink(full):
                    total += os.path.getsize(full)
            except OSError:
                pass
    return total

def find_packages():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages")
    found = []
    try:
        for name in os.listdir(base):
            if "whatsapp" in name.lower() or "5319275a" in name.lower():
                p = os.path.join(base, name)
                if os.path.isdir(p):
                    found.append(p)
    except OSError:
        pass
    return found

def inspect_processes(package_path):
    # Get the process table once, then trace parent-process relationships.
    # WebView2 is a shared runtime, so its executable name alone is NOT a blocker.
    ps = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process | "
        "Select-Object Name,ProcessId,ParentProcessId,CommandLine,ExecutablePath | "
        "ConvertTo-Json -Compress"
    )
    process = None
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        try:
            stdout, stderr = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.communicate(timeout=2)
            except Exception:
                pass
            return None, [], [], "Windows did not complete the process query within 8 seconds. The query was stopped. No files were deleted; cleanup remains disabled."
        if process.returncode != 0:
            return None, [], [], "Windows process query failed: %s" % (stderr.strip() or "unknown error")
        raw = stdout.strip()
        if not raw:
            items = []
        else:
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else [parsed]
    except Exception as exc:
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
        return None, [], [], "Could not inspect running processes: %s" % exc

    by_pid = {}
    for item in items:
        try:
            by_pid[int(item.get("ProcessId"))] = item
        except (TypeError, ValueError):
            pass

    pkg_lower = os.path.normcase(os.path.abspath(package_path)).lower()
    blockers, unrelated, unknown = [], [], []
    for item in items:
        name = str(item.get("Name") or "")
        if name.lower() == "whatsapp.exe":
            blockers.append("WhatsApp.exe (PID %s)" % item.get("ProcessId", "?"))
            continue
        if name.lower() != "msedgewebview2.exe":
            continue

        pid = item.get("ProcessId", "?")
        cmd = str(item.get("CommandLine") or "").lower()
        exe = str(item.get("ExecutablePath") or "").lower()
        evidence = []
        if pkg_lower in cmd or pkg_lower in exe:
            evidence.append("WhatsApp package path")
        if "ebwebview" in cmd or "ebwebview" in exe:
            evidence.append("EBWebView profile path")
        if "whatsapp" in cmd or "whatsapp" in exe:
            evidence.append("WhatsApp command/path marker")

        # Trace a limited parent chain. This catches a WebView2 child whose
        # own command line does not expose its profile directory.
        parent_id = item.get("ParentProcessId")
        visited = set()
        for _ in range(8):
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                break
            if parent_id in visited or parent_id not in by_pid:
                break
            visited.add(parent_id)
            parent = by_pid[parent_id]
            parent_name = str(parent.get("Name") or "")
            parent_cmd = str(parent.get("CommandLine") or "").lower()
            parent_exe = str(parent.get("ExecutablePath") or "").lower()
            if parent_name.lower() == "whatsapp.exe":
                evidence.append("WhatsApp.exe parent (PID %s)" % parent_id)
                break
            if pkg_lower in parent_cmd or pkg_lower in parent_exe or "ebwebview" in parent_cmd or "ebwebview" in parent_exe:
                evidence.append("WhatsApp package/profile in parent process (PID %s)" % parent_id)
                break
            parent_id = parent.get("ParentProcessId")

        if evidence:
            blockers.append("msedgewebview2.exe (PID %s; %s)" % (pid, "; ".join(evidence)))
        elif not cmd and not item.get("ExecutablePath"):
            unknown.append("msedgewebview2.exe (PID %s; Windows did not provide command line or executable path)" % pid)
        else:
            unrelated.append("msedgewebview2.exe (PID %s; no WhatsApp ownership evidence)" % pid)

    return True, blockers, unrelated, unknown, ""

class InspectorFrame(wx.Frame):
    def __init__(self, parent, package):
        super(InspectorFrame, self).__init__(
            parent, title="WhatsApp Cache Cleaner 1.10",
            size=(850, 590), style=wx.DEFAULT_FRAME_STYLE
        )
        self.package = package
        self.busy = False
        self.rows = []
        self.scan_valid = False
        self.process_check_passed = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            panel,
            label=("Three separate actions: 1. Scan storage. 2. Check processes (diagnostic only). "
                   "3. Clean cache (requires a successful scan and process check, then confirmation). "
                   "No force-closing or permission bypass. Close with Alt+F4.")
        )
        intro.Wrap(810)
        sizer.Add(intro, 0, wx.ALL | wx.EXPAND, 10)

        self.output = wx.TextCtrl(
            panel, value="First select Scan storage.",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        )
        sizer.Add(self.output, 1, wx.ALL | wx.EXPAND, 10)

        self.status = wx.StaticText(panel, label="Ready. No scan or process check has been performed.")
        sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.scan_button = wx.Button(panel, label="1. Scan storage")
        self.check_button = wx.Button(panel, label="2. Check processes")
        self.clean_button = wx.Button(panel, label="3. Clean cache")
        self.close_button = wx.Button(panel, label="Close")
        self.check_button.Enable(False)
        self.clean_button.Enable(False)
        for button in (self.scan_button, self.check_button, self.clean_button, self.close_button):
            row.Add(button, 0, wx.ALL, 5)
        sizer.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 5)
        panel.SetSizer(sizer)

        self.scan_button.Bind(wx.EVT_BUTTON, self.on_scan)
        self.check_button.Bind(wx.EVT_BUTTON, self.on_check)
        self.clean_button.Bind(wx.EVT_BUTTON, self.on_clean)
        self.close_button.Bind(wx.EVT_BUTTON, self.on_close)
        self.Bind(wx.EVT_CLOSE, self.on_close_event)

    def set_busy(self, message):
        self.busy = True
        self.status.SetLabel(message)
        for b in (self.scan_button, self.check_button, self.clean_button):
            b.Enable(False)

    def clear_busy(self):
        self.busy = False
        self.scan_button.Enable(True)
        self.check_button.Enable(self.scan_valid)
        self.clean_button.Enable(self.scan_valid and self.process_check_passed)

    def on_close(self, event):
        if self.busy:
            wx.MessageBox("Please wait for the current operation to finish.",
                          "WhatsApp Cache Cleaner", wx.OK | wx.ICON_INFORMATION)
            return
        self.Close()

    def on_close_event(self, event):
        if self.busy:
            event.Veto()
            return
        self.Destroy()

    def on_scan(self, event):
        if self.busy:
            return
        self.scan_valid = False
        self.process_check_passed = False
        self.rows = []
        self.check_button.Enable(False)
        self.clean_button.Enable(False)
        self.set_busy("Scanning recognised cache folders. Please wait.")
        self.output.SetValue("Scanning recognised cache folders...")
        package = self.package
        def worker():
            rows = []
            total = 0
            root = os.path.join(package, "LocalCache", "EBWebView")
            for rel, label in CACHE_RELATIVE:
                path = os.path.join(root, *rel.split("\\"))
                size = folder_size(path)
                if size > 0:
                    rows.append((rel, label, size))
                    total += size
            wx.CallAfter(self.scan_complete, rows, total)
        threading.Thread(target=worker, daemon=True).start()

    def scan_complete(self, rows, total):
        self.rows = rows
        self.scan_valid = True
        self.process_check_passed = False
        lines = ["WhatsApp cache scan complete.", ""]
        for rel, label, size in rows:
            lines.append("%s: %s" % (label, fmt(size)))
        lines += ["", "Approximate total found: %s" % fmt(total),
                  "", "Next: select '2. Check processes'. This check does not delete anything.",
                  "Protected: " + PROTECTED + "."]
        self.output.SetValue("\n".join(lines))
        self.output.SetInsertionPoint(0)
        self.clear_busy()
        self.status.SetLabel("Scan complete. Process check is still required before cleanup.")
        ui.message("WhatsApp storage scan complete. Next, check processes.")

    def on_check(self, event):
        if self.busy or not self.scan_valid:
            return
        self.process_check_passed = False
        self.clean_button.Enable(False)
        self.set_busy("Checking WhatsApp and WebView2 processes. No files will be deleted.")
        self.output.AppendText("\n\nChecking running processes. This action does not delete files...")
        package = self.package
        def worker():
            result = inspect_processes(package)
            wx.CallAfter(self.check_complete, result)
        threading.Thread(target=worker, daemon=True).start()

    def check_complete(self, result):
        ok, blockers, unrelated, unknown, error = result
        self.clear_busy()
        if ok is None:
            self.status.SetLabel("Process check failed. Cleanup remains disabled.")
            self.output.AppendText("\n\nPROCESS CHECK FAILED:\n" + str(error) +
                                    "\nNo files were deleted. Cleanup is disabled.")
            ui.message("Process check failed. No files were deleted.")
            return
        if blockers or unknown:
            self.status.SetLabel("WhatsApp-related or unidentified process detected. Cleanup is disabled.")
            if blockers:
                self.output.AppendText("\n\nWHATSAPP-RELATED PROCESSES DETECTED:\n" + "\n".join(blockers))
            if unknown:
                self.output.AppendText("\n\nUNIDENTIFIED WEBVIEW2 PROCESSES (safe ownership check unavailable):\n" + "\n".join(unknown))
            self.output.AppendText("\n\nNo files were deleted. Cleanup remains disabled for safety.")
            ui.message("WhatsApp-related or unidentified process detected. Cleanup is disabled.")
            return
        self.process_check_passed = True
        self.clean_button.Enable(True)
        self.status.SetLabel("No WhatsApp-related process detected. Cleanup is now available.")
        self.output.AppendText("\n\nPROCESS CHECK PASSED:\nNo WhatsApp.exe or WhatsApp-associated WebView2 process was detected.")
        if unrelated:
            self.output.AppendText("\n\nOther WebView2 processes (not identified as WhatsApp; these do not block cleanup):\n" + "\n".join(unrelated))
        self.output.AppendText("\n\nNo files were deleted by the process check.")
        ui.message("Process check passed. No WhatsApp-related process detected. Cleanup is available.")

    def on_clean(self, event):
        if self.busy or not self.scan_valid or not self.process_check_passed:
            return
        warning = [
            "You are about to clean these recognised cache folders:", ""
        ]
        for rel, label, size in self.rows:
            warning.append("%s: %s" % (label, fmt(size)))
        warning += [
            "", "Service Worker CacheStorage may contain cached app resources or media.",
            "WhatsApp may need to download some content again.",
            "", "The process check passed, but please ensure WhatsApp remains closed.",
            "Windows may still deny access to files. This tool will not bypass permissions.",
            "Protected chat databases, IndexedDB, cookies and account/session data will not be deleted.",
            "", "Do you want to clean these cache folders?"
        ]
        dlg = wx.MessageDialog(
            self, "\n".join(warning), "Confirm WhatsApp cache cleanup",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
        )
        try:
            answer = dlg.ShowModal()
        finally:
            dlg.Destroy()
        if answer != wx.ID_YES:
            self.status.SetLabel("Cleanup cancelled. No files were deleted.")
            ui.message("Cleanup cancelled. No files were deleted.")
            return

        self.set_busy("Cleaning recognised cache folders and measuring results.")
        package = self.package
        rows_copy = list(self.rows)
        def worker():
            results = []
            for rel, label, scanned_size in rows_copy:
                target = os.path.abspath(os.path.join(
                    package, "LocalCache", "EBWebView", *rel.split("\\")
                ))
                allowed_root = os.path.abspath(os.path.join(
                    package, "LocalCache", "EBWebView"
                ))
                if not target.startswith(allowed_root + os.sep):
                    results.append((label, 0, 0, "Safety path check failed"))
                    continue
                before = folder_size(target)
                error = ""
                if os.path.isdir(target):
                    try:
                        shutil.rmtree(target)
                    except Exception as exc:
                        error = str(exc)
                after = folder_size(target)
                removed = max(0, before - after)
                if os.path.exists(target):
                    state = "Partly remains" if removed else "Not removed"
                    if error:
                        state += " (" + error + ")"
                else:
                    state = "Folder removed"
                results.append((label, before, removed, state))
            wx.CallAfter(self.clean_complete, results)
        threading.Thread(target=worker, daemon=True).start()

    def clean_complete(self, results):
        self.clear_busy()
        self.scan_valid = False
        self.process_check_passed = False
        self.clean_button.Enable(False)
        self.check_button.Enable(False)
        removed_total = sum(item[2] for item in results)
        lines = ["Cleanup attempt finished.", "",
                 "Measured data removed: %s" % fmt(removed_total), ""]
        for label, before, removed, state in results:
            lines.append("%s: removed %s; %s" % (label, fmt(removed), state))
        lines += ["", "Run a new scan to verify remaining cache.",
                  "A folder marked 'Partly remains' or 'Not removed' needs attention."]
        self.output.SetValue("\n".join(lines))
        self.output.SetInsertionPoint(0)
        self.status.SetLabel("Cleanup finished. Scan again to verify.")
        ui.message("Cleanup finished. Measured data removed: %s." % fmt(removed_total))

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "WhatsApp Cache Cleaner"
    __gestures = {"kb:NVDA+shift+w": "script_openInspector"}

    def __init__(self):
        super(GlobalPlugin, self).__init__()
        self.frame = None
        self.menu = gui.mainFrame.sysTrayIcon.toolsMenu
        self.menu_item = self.menu.Append(wx.ID_ANY, "WhatsApp Cache Cleaner 1.10...")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.on_menu, self.menu_item)

    def terminate(self):
        try:
            gui.mainFrame.sysTrayIcon.Unbind(
                wx.EVT_MENU, handler=self.on_menu, id=self.menu_item.GetId()
            )
            self.menu.Remove(self.menu_item)
        except Exception:
            pass
        if self.frame:
            try:
                self.frame.Destroy()
            except Exception:
                pass
        super(GlobalPlugin, self).terminate()

    def on_menu(self, event):
        self.open_inspector()

    @script(description="Open WhatsApp Cache Cleaner 1.10")
    def script_openInspector(self, gesture):
        self.open_inspector()

    def open_inspector(self):
        if self.frame:
            try:
                if self.frame.IsShown():
                    self.frame.Raise()
                    return
            except Exception:
                self.frame = None
        packages = find_packages()
        if not packages:
            wx.MessageBox("Microsoft Store WhatsApp package was not found.",
                          "WhatsApp Cache Cleaner", wx.OK | wx.ICON_WARNING)
            return
        self.frame = InspectorFrame(gui.mainFrame, packages[0])
        self.frame.Show()
        self.frame.Raise()
