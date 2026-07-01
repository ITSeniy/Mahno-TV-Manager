"""Supervises the always-on director processes for a broadcast session:
run_playout (the OBS playout controller) and run_ticker (the ticker HTTP
server + daily Gemini refresh). Restarts either one if it crashes, with
exponential backoff so a persistent failure (e.g. OBS not reachable yet)
doesn't spin in a tight loop. Also opens the local output window once at
startup - see output_window.py for why that's not part of the managed
processes' own bootstrap.

Expects OBS to already be running with the WebSocket server enabled.

Usage:
    OBS_WS_PASSWORD=... .venv/Scripts/python.exe -m director.supervisor
"""

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from director.obs_client import get_client
from director.output_window import open_program_projector

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = REPO_ROOT / "logs"

MANAGED_MODULES = ["director.run_playout", "director.run_ticker", "director.run_dashboard"]

MIN_BACKOFF_SECONDS = 3.0
MAX_BACKOFF_SECONDS = 120.0
HEALTHY_UPTIME_SECONDS = 60.0  # running this long without crashing resets backoff to the minimum
POLL_INTERVAL_SECONDS = 5


def next_backoff(current: float) -> float:
    return min(current * 2, MAX_BACKOFF_SECONDS)


class ManagedProcess:
    def __init__(self, module: str):
        self.module = module
        self.proc: subprocess.Popen | None = None
        self.backoff = MIN_BACKOFF_SECONDS
        self.started_at = 0.0
        self.log_path = LOG_DIR / f"{module.replace('.', '_')}.log"

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(self.log_path, "a", encoding="utf-8")
        log_file.write(f"\n--- starting {self.module} at {datetime.now(timezone.utc).isoformat()} ---\n")
        log_file.flush()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", self.module],
            cwd=REPO_ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        self.started_at = time.monotonic()
        print(f"[supervisor] started {self.module} (pid {self.proc.pid}), logging to {self.log_path}")

    def poll_and_maybe_restart(self) -> None:
        if self.is_running():
            if time.monotonic() - self.started_at > HEALTHY_UPTIME_SECONDS:
                self.backoff = MIN_BACKOFF_SECONDS
            return

        exit_code = self.proc.returncode if self.proc else None
        print(f"[supervisor] {self.module} exited (code {exit_code}), restarting in {self.backoff:.0f}s")
        time.sleep(self.backoff)
        self.backoff = next_backoff(self.backoff)
        self.start()

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


def main() -> None:
    client = get_client()
    open_program_projector(client)
    print("[supervisor] output window opened")

    managed = [ManagedProcess(m) for m in MANAGED_MODULES]
    for m in managed:
        m.start()

    print("[supervisor] watching over the channel (Ctrl+C to stop everything)")
    try:
        while True:
            time.sleep(POLL_INTERVAL_SECONDS)
            for m in managed:
                m.poll_and_maybe_restart()
    except KeyboardInterrupt:
        print("[supervisor] shutting down managed processes")
    finally:
        for m in managed:
            m.stop()


if __name__ == "__main__":
    main()
