"""Supervise the B2 application process and create timestamped session logs."""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import APP_DIR, ensure_runtime_dirs
def main():
    ensure_runtime_dirs()
    log_dir = Path(os.environ.get("B2_LOG_DIR", "/var/log/b2-droid"))
    log_dir.mkdir(parents=True, exist_ok=True)
    while True:
        date = datetime.now().strftime("%Y-%m-%d")
        existing = list(log_dir.glob(f"{date}-*.log"))
        numbers = []
        for path in existing:
            try:
                numbers.append(int(path.stem.rsplit("-", 1)[1]))
            except ValueError:
                pass
        session_path = log_dir / f"{date}-{max(numbers, default=0) + 1}.log"
        process = subprocess.Popen(
            [sys.executable, str(APP_DIR / "droid.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        print(
            f"Droid process started with PID {process.pid}; session log {session_path}",
            flush=True,
        )

        def copy_output():
            with session_path.open("a", encoding="utf-8") as session:
                for line in process.stdout:
                    timestamp = datetime.now().astimezone().isoformat(
                        timespec="milliseconds"
                    )
                    rendered = f"[{timestamp}] {line}" if line.strip() else line
                    session.write(rendered)
                    session.flush()
                    print(rendered, end="", flush=True)

        output_thread = threading.Thread(target=copy_output, daemon=True)
        output_thread.start()
        while process.poll() is None:
            time.sleep(5)
        output_thread.join(timeout=2)
        if process.returncode not in (None, 0):
            print(f"Droid exited with {process.returncode}; restarting", flush=True)
            time.sleep(3)
        elif process.returncode == 0:
            print("Droid exited cleanly; restarting", flush=True)


if __name__ == "__main__":
    main()
