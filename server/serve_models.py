"""Run selected registry model servers as one supervised foreground process."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path

import httpx

from server import registry


DEFAULT_BINARIES = {
    "llamacpp": "~/src/llama.cpp/build/bin/llama-server",
    "bitnetcpp": "~/src/BitNet/build/bin/llama-server",
}


def runtime_binary(runtime: str) -> Path:
    value = os.environ.get(
        f"VINFER_{runtime.upper()}_SERVER", DEFAULT_BINARIES.get(runtime, "")
    )
    if not value:
        raise ValueError(f"no server binary configured for runtime {runtime!r}")
    return Path(value).expanduser()


def launch_command(
    model: registry.ModelEntry, threads: int, context_cap: int, parallel: int = 1
) -> list[str]:
    command = [
        str(runtime_binary(model.runtime)),
        "-m",
        model.weights,
        "--port",
        str(model.port),
        "--host",
        "127.0.0.1",
        "-t",
        str(threads),
        "-c",
        str(min(model.ctx_max, context_cap)),
        "--no-warmup",
        "--log-disable",
    ]
    if parallel > 1:
        command.extend(("--parallel", str(parallel), "--cont-batching"))
    if model.chat_template == "jinja":
        command.append("--jinja")
    return command


def runtime_environment(model: registry.ModelEntry) -> dict[str, str]:
    environment = os.environ.copy()
    runtime_dir = str(runtime_binary(model.runtime).parent)
    existing = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = (
        f"{runtime_dir}:{existing}" if existing else runtime_dir
    )
    return environment


def healthy(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).is_success
    except httpx.HTTPError:
        return False


def wait_until_healthy(
    entries: dict[str, registry.ModelEntry], ids: list[str], timeout: int
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(healthy(entries[model_id].port) for model_id in ids):
            return True
        time.sleep(2)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models", help="comma-separated registry IDs; default is every servable entry"
    )
    parser.add_argument("--threads", type=int, default=64)
    parser.add_argument("--context-cap", type=int, default=8192)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument(
        "--status",
        action="store_true",
        help="wait for the selected registry runtimes to become healthy and exit",
    )
    parser.add_argument("--startup-timeout", type=int, default=900)
    args = parser.parse_args()
    for name in ("threads", "context_cap", "parallel", "startup_timeout"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    entries = registry.load()
    ids = (
        [value.strip() for value in args.models.split(",") if value.strip()]
        if args.models
        else registry.servable_ids(entries)
    )
    unknown = sorted(set(ids) - set(entries))
    if unknown:
        parser.error(f"unknown model IDs: {unknown}")
    if not ids:
        parser.error("at least one model is required")
    if args.status:
        if not wait_until_healthy(entries, ids, args.startup_timeout):
            raise RuntimeError("selected model runtimes are not healthy")
        return

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
            command = launch_command(
                model, args.threads, args.context_cap, parallel=args.parallel
            )
            processes.append(subprocess.Popen(command, env=runtime_environment(model)))

        deadline = time.monotonic() + args.startup_timeout
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
