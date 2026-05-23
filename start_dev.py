import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PYTHON = BACKEND / "venv" / "Scripts" / "python.exe"
ALEMBIC = BACKEND / "venv" / "Scripts" / "alembic.exe"

processes: list[tuple[str, subprocess.Popen]] = []


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def require_path(path: Path, message: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{message}: {path}")


def run_once(command: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def start_process(name: str, command: list[str], cwd: Path) -> None:
    print(f"Starting {name}: {' '.join(command)}", flush=True)
    process = subprocess.Popen(command, cwd=cwd)
    processes.append((name, process))


def stop_processes() -> None:
    for name, process in reversed(processes):
        if process.poll() is not None:
            continue

        print(f"Stopping {name} (PID {process.pid})...", flush=True)
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def stop_docker_services() -> None:
    subprocess.run(["docker", "compose", "stop"], cwd=ROOT, check=False)


def main() -> int:
    require_path(PYTHON, "Backend virtual environment was not found")
    require_path(ALEMBIC, "Alembic executable was not found")
    require_path(FRONTEND / "package.json", "Frontend package.json was not found")

    try:
        step("Starting Postgres and Redis")
        run_once(["docker", "compose", "up", "-d"], ROOT)

        step("Applying database migrations")
        run_once([str(ALEMBIC), "upgrade", "head"], ROOT)

        step("Starting backend, worker, and frontend")
        start_process(
            "backend API",
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "main:app",
                "--reload",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            BACKEND,
        )
        start_process("RQ worker", [str(PYTHON), "worker.py"], BACKEND)
        start_process(
            "frontend",
            ["npm", "run", "dev", "--", "--host", "127.0.0.1"],
            FRONTEND,
        )

        print("\nPDReader is running.", flush=True)
        print("Frontend: http://127.0.0.1:5173", flush=True)
        print("Backend:  http://127.0.0.1:8000", flush=True)
        print("\nPress Ctrl+C to stop everything.", flush=True)

        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"{name} stopped unexpectedly with exit code {exit_code}")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\nStop requested.", flush=True)
        return 0
    finally:
        step("Stopping app services")
        stop_processes()
        step("Stopping Docker services")
        stop_docker_services()
        print("\nAll PDReader services stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
