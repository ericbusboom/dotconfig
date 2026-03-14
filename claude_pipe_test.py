#!/usr/bin/env python3
"""
Test program: pipe questions to a Claude Code session via stream-json mode
and pretty-print each JSON line received.

Goal: discover whether claude --print terminates after answering or waits
for follow-up input.
"""

import json
import subprocess
import sys
import threading
import time

QUESTIONS = [
    "How does this app parse args?",
    "What CLI commands does it support?",
    "How are secrets handled?",
]

HR = "\n" + "=" * 72 + "\n"


def reader(proc: subprocess.Popen):
    """Read stdout line-by-line, pretty-print each JSON object."""
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            print(HR)
            print(json.dumps(obj, indent=2))
        except json.JSONDecodeError:
            print(HR)
            print(f"[non-json] {line}")
    print(HR)
    print("[reader] stdout closed — claude process ended")


def main():
    cmd = [
        "claude",
        "--output-format", "stream-json",
        "--print",
        "--verbose",
    ]

    print(f"[main] Starting: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line-buffered
    )

    # Read stdout in a background thread so we never block
    t = threading.Thread(target=reader, args=(proc,), daemon=True)
    t.start()

    # Also drain stderr in background so it doesn't block
    def stderr_reader():
        for line in proc.stderr:
            print(f"[stderr] {line.rstrip()}", file=sys.stderr)

    t_err = threading.Thread(target=stderr_reader, daemon=True)
    t_err.start()

    for i, question in enumerate(QUESTIONS):
        print(f"\n{'#' * 72}")
        print(f"# SENDING QUESTION {i + 1}: {question}")
        print(f"{'#' * 72}\n")

        proc.stdin.write(question + "\n")
        proc.stdin.flush()

        # Give claude time to process and respond
        # We'll watch for activity to stop
        time.sleep(15)

        # Check if process has already exited
        ret = proc.poll()
        if ret is not None:
            print(f"\n[main] claude exited with code {ret} after question {i + 1}")
            break
    else:
        # All questions sent — wait a bit then check
        print(f"\n[main] All {len(QUESTIONS)} questions sent. Waiting for final output...")
        time.sleep(10)
        ret = proc.poll()
        if ret is not None:
            print(f"[main] claude exited with code {ret}")
        else:
            print("[main] claude is STILL RUNNING — it appears to wait for more input")
            print("[main] Closing stdin to signal EOF...")
            proc.stdin.close()
            proc.wait(timeout=30)
            print(f"[main] claude exited with code {proc.returncode}")

    # Let reader thread finish draining
    t.join(timeout=5)
    print("\n[main] Done.")


if __name__ == "__main__":
    main()
