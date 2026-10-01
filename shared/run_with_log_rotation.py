#!/usr/bin/env python3
"""Run a subprocess and rotate its combined stdout/stderr log by size."""

import argparse
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path


DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10


class SizeRotatingWriter:
    """Write raw bytes to a file and rotate it when it exceeds a size limit."""

    def __init__(self, log_file: Path, max_bytes: int, backup_count: int) -> None:
        self.log_file = log_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.log_file.open("ab")

    def write(self, data: bytes) -> None:
        if not data:
            return

        with self._lock:
            if self.max_bytes <= 0:
                self._stream.write(data)
                self._stream.flush()
                return

            offset = 0
            data_length = len(data)
            while offset < data_length:
                self._stream.seek(0, os.SEEK_END)
                current_size = self._stream.tell()

                if current_size >= self.max_bytes and current_size > 0:
                    self._rotate()
                    continue

                remaining_capacity = self.max_bytes - current_size
                chunk = data[offset : offset + remaining_capacity]
                self._stream.write(chunk)
                self._stream.flush()
                offset += len(chunk)

    def close(self) -> None:
        with self._lock:
            self._stream.close()

    def _rotate(self) -> None:
        self._stream.close()

        if self.backup_count > 0:
            oldest_backup = self.log_file.with_name(f"{self.log_file.name}.{self.backup_count}")
            if oldest_backup.exists():
                oldest_backup.unlink()

            for index in range(self.backup_count - 1, 0, -1):
                src = self.log_file.with_name(f"{self.log_file.name}.{index}")
                dst = self.log_file.with_name(f"{self.log_file.name}.{index + 1}")
                if src.exists():
                    src.replace(dst)

            if self.log_file.exists():
                self.log_file.replace(self.log_file.with_name(f"{self.log_file.name}.1"))
        elif self.log_file.exists():
            self.log_file.unlink()

        self._stream = self.log_file.open("ab")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a command and rotate its combined stdout/stderr log by size."
    )
    parser.add_argument("--log-file", required=True, help="Path to the active log file.")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Rotate after this many bytes (default: {DEFAULT_MAX_BYTES}).",
    )
    parser.add_argument(
        "--backup-count",
        type=int,
        default=DEFAULT_BACKUP_COUNT,
        help=f"Number of rotated backups to keep (default: {DEFAULT_BACKUP_COUNT}).",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to execute. Prefix with -- to separate wrapper args.",
    )

    args = parser.parse_args()
    if not args.command:
        parser.error("a command is required")

    if args.command[0] == "--":
        args.command = args.command[1:]

    if not args.command:
        parser.error("a command is required after --")

    return args


def main() -> int:
    args = parse_args()
    log_writer = SizeRotatingWriter(
        log_file=Path(args.log_file),
        max_bytes=args.max_bytes,
        backup_count=args.backup_count,
    )

    child = subprocess.Popen(
        args.command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    def forward_signal(signum: int, _frame: object) -> None:
        if child.poll() is not None:
            return
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    assert child.stdout is not None
    try:
        for chunk in iter(lambda: child.stdout.read(65536), b""):
            log_writer.write(chunk)
    finally:
        child.stdout.close()
        return_code = child.wait()
        log_writer.close()

    return return_code


if __name__ == "__main__":
    sys.exit(main())
