"""Entry point: `python -m jobhuntr` (or JobHuntr.exe). Starts the local server and opens the app window."""
import argparse
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser

import requests
from werkzeug.serving import make_server

from . import __version__, extract, system
from .crawler import Crawler
from .db import Database
from .matching import Search, group_similar
from .paths import data_dir
from .web import create_app

PORT = 8765
# Quit when every app window has said goodbye and nothing has called the API for a bit. Background/minimized
# windows get their timers throttled (to ~1/min), so missed heartbeats alone must never stop the server.
CLOSE_GRACE_SECONDS = 15
NO_WINDOW_YET_SECONDS = 600       # window never connected (e.g. browser failed to open)
IDLE_SHUTDOWN_SECONDS = 12 * 3600  # safety net for windows that vanished without saying goodbye
EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_window(url):
    """Open as a standalone app window (Edge/Chrome --app) so it feels like a desktop program."""
    candidates = EDGE_PATHS + [shutil.which("msedge") or "", shutil.which("chrome") or ""]
    for exe in candidates:
        if exe and os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1320,900"])
            return
    webbrowser.open(url)


def headless_crawl(db, crawler, port):
    """Used by the daily scheduled task: crawl, then pop a Windows notification about new matches."""
    if port_in_use(port):
        # The app is open: let its server run the crawl so both don't write at once.
        base = f"http://127.0.0.1:{port}/api/crawl"
        requests.post(base, timeout=10)
        while requests.get(base, timeout=10).json().get("running"):
            time.sleep(5)
    else:
        crawler.start()
        crawler._thread.join()
    last = db.get_setting("last_run") or {}
    matches = new_matches(db, last.get("started_at"))
    if matches:
        top = "; ".join(f"{j['title']} ({j['company']})" for j in matches[:3])
        more = f" +{len(matches) - 3} more" if len(matches) > 3 else ""
        system.notify(f"JobHuntr: {len(matches)} new job match{'es' if len(matches) != 1 else ''}", top + more)
    print(f"Crawl finished: {len(matches)} new matching jobs")


def new_matches(db, started_at):
    if not started_at or len(db.runs(2)) < 2:  # the very first crawl finds "everything"; don't spam
        return []
    searches = [Search(r) for r in db.searches()]
    hits = [j for j in db.jobs_for_matching() if j["active"] and j["first_seen"] >= started_at
            and any(s.match(j) for s in searches)]
    return sorted(group_similar(hits), key=lambda j: j["title"])


def main():
    parser = argparse.ArgumentParser(prog="jobhuntr", description="JobHuntr job crawler and application tracker")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-window", action="store_true", help="don't open the app window")
    parser.add_argument("--crawl", action="store_true", help="run one crawl headless and exit (for Task Scheduler)")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"

    db = Database(data_dir() / "jobhuntr.db")
    crawler = Crawler(db)

    if args.crawl:
        db.reanalyze(extract.analyze, extract.VERSION)
        headless_crawl(db, crawler, args.port)
        return

    if port_in_use(args.port):  # already running: just bring up another window
        open_window(url)
        return

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app(db, crawler)
    server = make_server("127.0.0.1", args.port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # re-score stored jobs after an update without making the window wait
    threading.Thread(target=db.reanalyze, args=(extract.analyze, extract.VERSION), daemon=True, name="reanalyze").start()
    print(f"JobHuntr {__version__} running at {url}  (data: {data_dir()})")
    if not args.no_window:
        open_window(url)

    started = time.time()
    try:
        while True:
            time.sleep(2)
            if args.no_window or crawler.status().get("running"):
                continue
            life = app.config["lifecycle"]
            idle = time.time() - life.last_request
            all_closed = life.ever_connected and not life.open_windows() and idle > CLOSE_GRACE_SECONDS
            never_opened = not life.ever_connected and time.time() - started > NO_WINDOW_YET_SECONDS
            if all_closed or never_opened or idle > IDLE_SHUTDOWN_SECONDS:
                break
    except KeyboardInterrupt:
        pass
    server.shutdown()
    os._exit(0)  # don't wait on stray worker threads


if __name__ == "__main__":
    main()
