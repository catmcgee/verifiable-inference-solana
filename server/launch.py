"""Launch one local model server per servable models.yaml entry."""

from __future__ import annotations

import argparse
import os
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
    env_name = f"VINFER_{runtime.upper()}_SERVER"
    value = os.environ.get(env_name, DEFAULT_BINARIES.get(runtime, ""))
    if not value:
        raise ValueError(f"no server binary configured for runtime {runtime!r}")
    return Path(value).expanduser()


def launch_command(
    model: registry.ModelEntry, threads: int, context_cap: int
) -> list[str]:
    context = min(model.ctx_max, context_cap)
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
        str(context),
        "--no-warmup",
        "--log-disable",
    ]
    if model.chat_template == "jinja":
        command.append("--jinja")
    return command


def runtime_environment(model: registry.ModelEntry) -> dict[str, str]:
    """Resolve shared libraries shipped beside a registry runtime binary."""
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


def launch(models: list[registry.ModelEntry], threads: int, context_cap: int) -> None:
    logs = Path(os.environ.get("VINFER_MODEL_LOG_DIR", "~/logs")).expanduser()
    logs.mkdir(parents=True, exist_ok=True)
    started: list[registry.ModelEntry] = []
    for model in models:
        if healthy(model.port):
            print(f"{model.id} already healthy on :{model.port}")
            continue
        binary = runtime_binary(model.runtime)
        weights = Path(model.weights)
        if not binary.is_file():
            raise FileNotFoundError(f"runtime binary not found: {binary}")
        if not weights.is_file():
            raise FileNotFoundError(f"weights not found for {model.id}: {weights}")
        logfile = (logs / f"{model.id}.log").open("ab", buffering=0)
        subprocess.Popen(
            launch_command(model, threads, context_cap),
            env=runtime_environment(model),
            stdin=subprocess.DEVNULL,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        logfile.close()
        started.append(model)
        print(f"started {model.id} on :{model.port}")

    deadline = time.monotonic() + 600
    pending = {model.id: model for model in started}
    while pending and time.monotonic() < deadline:
        for model_id, model in list(pending.items()):
            if healthy(model.port):
                print(f"{model.id} healthy on :{model.port}")
                pending.pop(model_id)
        if pending:
            time.sleep(2)
    if pending:
        raise RuntimeError(f"model runtimes did not become healthy: {sorted(pending)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=64)
    parser.add_argument(
        "--context-cap",
        type=int,
        default=int(os.environ.get("VINFER_SERVER_CONTEXT_CAP", "16384")),
    )
    parser.add_argument(
        "--models", help="comma-separated registry IDs; default is every servable entry"
    )
    args = parser.parse_args()
    entries = registry.load()
    selected = (
        [item.strip() for item in args.models.split(",") if item.strip()]
        if args.models
        else [model.id for model in entries.values() if model.servable]
    )
    unknown = sorted(set(selected) - set(entries))
    if unknown:
        parser.error(f"unknown model IDs: {unknown}")
    launch([entries[model_id] for model_id in selected], args.threads, args.context_cap)


if __name__ == "__main__":
    main()
