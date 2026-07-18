"""Run selected registry model servers as one supervised foreground process."""

from __future__ import annotations

import argparse
import signal
import subprocess
import time

from server import registry
from server.launch import healthy, launch_command, runtime_environment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models", help="comma-separated registry IDs; default is every servable entry"
    )
    parser.add_argument("--threads", type=int, default=64)
    parser.add_argument("--context-cap", type=int, default=8192)
    args = parser.parse_args()
    entries = registry.load()
    ids = (
        [value.strip() for value in args.models.split(",") if value.strip()]
        if args.models
        else registry.servable_ids(entries)
    )
    unknown = sorted(set(ids) - set(entries))
    if unknown:
        parser.error(f"unknown model IDs: {unknown}")

    processes: list[subprocess.Popen] = []
    stopping = False

    def stop(_signum=None, _frame=None) -> None:
        nonlocal stopping
        stopping = True
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        for model_id in ids:
            model = entries[model_id]
            if healthy(model.port):
                raise RuntimeError(
                    f"port {model.port} for {model_id} is already healthy"
                )
            command = launch_command(model, args.threads, args.context_cap)
            processes.append(subprocess.Popen(command, env=runtime_environment(model)))

        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            exited = [
                ids[index]
                for index, process in enumerate(processes)
                if process.poll() is not None
            ]
            if exited:
                raise RuntimeError(f"model processes exited during startup: {exited}")
            if all(healthy(entries[model_id].port) for model_id in ids):
                break
            time.sleep(2)
        else:
            raise RuntimeError(
                "model servers did not become healthy before the deadline"
            )

        while not stopping:
            exited = [
                ids[index]
                for index, process in enumerate(processes)
                if process.poll() is not None
            ]
            if exited:
                raise RuntimeError(f"model processes exited: {exited}")
            time.sleep(2)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
