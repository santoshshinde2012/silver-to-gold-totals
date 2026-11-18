"""Capture the exported HTML report with a locally installed Chrome/Chromium."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, default=Path("docs/results/index.html"))
    parser.add_argument("--output", type=Path, default=Path("docs/results/snapshot.png"))
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1230)
    args = parser.parse_args()
    if args.width < 640 or args.height < 480:
        parser.error("Use a capture size of at least 640 × 480 pixels.")
    if not args.html.is_file():
        parser.error(f"Report not found: {args.html}. Run python -m src.inspection first.")
    candidates = [
        os.environ.get("CHROME_BIN", ""),
        "google-chrome",
        "chromium",
        "chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    browser = next((found for candidate in candidates if candidate and (found := shutil.which(candidate))), None)
    if browser is None:
        parser.error("Install Chrome/Chromium or set CHROME_BIN to its executable path.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="totals-snapshot-") as profile:
        capture = Path(profile) / "snapshot.png"
        command = [
            browser,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--force-device-scale-factor=1",
            f"--window-size={args.width},{args.height}",
            f"--user-data-dir={Path(profile) / 'browser'}",
            f"--screenshot={capture}",
            args.html.resolve().as_uri(),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
        except (OSError, subprocess.SubprocessError) as exc:
            parser.exit(1, f"Snapshot failed: {exc}\n")
        if not capture.is_file():
            parser.exit(1, "Chrome exited without creating the screenshot.\n")
        shutil.copyfile(capture, args.output)
    print(f"Snapshot saved to {args.output}")


if __name__ == "__main__":
    main()
