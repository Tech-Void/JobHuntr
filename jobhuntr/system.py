"""Windows integration: the daily crawl scheduled task and toast notifications."""
import re
import subprocess
import sys
from pathlib import Path

TASK_NAME = "JobHuntr Daily Crawl"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: don't flash a console


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)


def crawl_command():
    """Command line that runs one headless crawl, for this install (exe or source)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --crawl'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = Path(__file__).resolve().parent.parent / "run_jobhuntr.py"
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{launcher}" --crawl'


def schedule_status():
    r = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    if r.returncode != 0:
        return {"enabled": False, "time": "08:00"}
    start = re.search(r"Start Time:\s*(\d{1,2}):(\d{2})", r.stdout)
    next_run = re.search(r"Next Run Time:\s*(.+)", r.stdout)
    return {"enabled": True, "time": f"{int(start.group(1)):02d}:{start.group(2)}" if start else "08:00",
            "next_run": next_run.group(1).strip() if next_run else ""}


def set_schedule(enabled: bool, time_hhmm: str = "08:00"):
    if not enabled:
        _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        return schedule_status()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_hhmm or ""):
        raise ValueError("Time must look like 08:00")
    r = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", crawl_command(), "/SC", "DAILY",
              "/ST", time_hhmm, "/F"])
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "Windows refused to create the scheduled task")
    return schedule_status()


def notify(title: str, body: str):
    """Show a Windows toast notification (best effort; silently does nothing if it can't)."""
    def ps_quote(s):
        return "'" + s.replace("'", "''") + "'"
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$t = [System.Security.SecurityElement]::Escape({ps_quote(title)})
$b = [System.Security.SecurityElement]::Escape({ps_quote(body)})
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>")
$app = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    try:
        _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=20)
    except Exception:  # noqa: BLE001 - notifications are a nice-to-have
        pass
