"""SimpliSolar unified launcher.

Starts both the backend (uvicorn) and frontend (Vite) in a single console
window with coloured status output and backend log streaming.

Usage:
    python launcher.py              # normal start
    python launcher.py --no-browser # skip auto-opening browser

Designed to be packaged later with PyInstaller:
    pyinstaller --onefile --name SimpliSolar launcher.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8001
FRONTEND_PORT = 5173
ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "frontend")

# ---------------------------------------------------------------------------
# Windows ANSI colour support
# ---------------------------------------------------------------------------

def _enable_ansi():
    """Enable ANSI escape sequences on Windows 10+."""
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass

_enable_ansi()

# ANSI codes
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
DIM     = "\033[90m"
BOLD    = "\033[1m"
RESET   = "\033[0m"
CLEAR_LINE = "\033[2K\r"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = f"""{CYAN}
  ███████╗██╗███╗   ███╗██████╗ ██╗     ██╗███████╗ ██████╗ ██╗      █████╗ ██████╗
  ██╔════╝██║████╗ ████║██╔══██╗██║     ██║██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗
  ███████╗██║██╔████╔██║██████╔╝██║     ██║███████╗██║   ██║██║     ███████║██████╔╝
  ╚════██║██║██║╚██╔╝██║██╔═══╝ ██║     ██║╚════██║██║   ██║██║     ██╔══██║██╔══██╗
  ███████║██║██║ ╚═╝ ██║██║     ███████╗██║███████║╚██████╔╝███████╗██║  ██║██║  ██║
  ╚══════╝╚═╝╚═╝     ╚═╝╚═╝     ╚══════╝╚═╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
{RESET}
  {DIM}Multi-view shadow engine for DJI RTK drone imagery{RESET}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_listening(port: int) -> bool:
    """Check if a port is listening, trying both IPv4 and IPv6."""
    for family, addr in [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((addr, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def _wait_for_ports(
    ports: dict[str, int],
    timeout: float = 30.0,
) -> dict[str, bool]:
    """Wait for multiple named ports in parallel with a progress bar.

    Returns a dict mapping name → whether it came up.
    """
    ready = {name: False for name in ports}
    deadline = time.monotonic() + timeout
    bar_chars = "░▒▓█"

    while time.monotonic() < deadline and not all(ready.values()):
        for name, port in ports.items():
            if not ready[name] and _port_listening(port):
                ready[name] = True

        # Progress bar
        elapsed = time.monotonic() + timeout - deadline  # seconds since start
        progress = min(elapsed / timeout, 1.0)
        bar_width = 30
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)

        parts = []
        for name, up in ready.items():
            if up:
                parts.append(f"{GREEN}✓ {name}{RESET}")
            else:
                parts.append(f"{DIM}⏳ {name}{RESET}")
        status_text = "  ".join(parts)

        print(f"{CLEAR_LINE}  {DIM}[{bar}]{RESET}  {status_text}", end="", flush=True)

        if all(ready.values()):
            break
        time.sleep(0.3)

    # Final line
    print(f"{CLEAR_LINE}", end="")
    return ready


def _kill_port(port: int):
    """Kill processes listening on a port (Windows)."""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid > 0:
                    print(f"  {YELLOW}Stopping PID {pid} on port {port}{RESET}")
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                    )
    except Exception:
        pass


def _status(msg: str, colour: str = GREEN):
    print(f"  {colour}{msg}{RESET}")


# ---------------------------------------------------------------------------
# Frontend subprocess
# ---------------------------------------------------------------------------

_frontend_proc: subprocess.Popen | None = None
_backend_ready = threading.Event()


def _start_frontend() -> subprocess.Popen:
    """Start Vite dev server as a background subprocess."""
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    proc = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    return proc


def _stream_frontend(proc: subprocess.Popen):
    """Read frontend output, show startup messages, suppress proxy noise."""
    try:
        for line in proc.stdout:
            stripped = line.strip()
            if not stripped:
                continue

            lower = stripped.lower()

            # Always show Vite startup confirmation
            if "ready in" in lower:
                print(f"  {DIM}[frontend] {stripped}{RESET}")
                continue

            # Suppress proxy errors until backend is up — they're expected
            if "econnrefused" in lower or "http proxy error" in lower:
                if not _backend_ready.is_set():
                    continue  # silently skip

            # Show real errors/warnings
            if any(kw in lower for kw in ("error", "warn", "failed")):
                print(f"  {DIM}[frontend] {stripped}{RESET}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Backend (uvicorn in a thread)
# ---------------------------------------------------------------------------

def _run_backend():
    """Run the uvicorn server (blocking)."""
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        log_level="info",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _frontend_proc

    open_browser = "--no-browser" not in sys.argv

    print(BANNER)

    # ── Clean up stale processes ──────────────────────────────────────────
    stale = _port_listening(BACKEND_PORT) or _port_listening(FRONTEND_PORT)
    if stale:
        _status("Stopping previous instances...", YELLOW)
        _kill_port(BACKEND_PORT)
        _kill_port(FRONTEND_PORT)
        time.sleep(0.8)

    # ── Start both services in parallel ───────────────────────────────────
    _status("Starting services...", DIM)
    print()

    # Frontend (subprocess)
    try:
        _frontend_proc = _start_frontend()
        threading.Thread(target=_stream_frontend, args=(_frontend_proc,), daemon=True).start()
    except FileNotFoundError:
        _status("ERROR: npm not found. Install Node.js from nodejs.org", RED)
        _status("Then run: cd frontend && npm install", YELLOW)
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Backend (thread — so both come up simultaneously)
    backend_thread = threading.Thread(target=_run_backend, daemon=True)
    backend_thread.start()

    # ── Wait for both with progress bar ───────────────────────────────────
    ready = _wait_for_ports({"Backend": BACKEND_PORT, "Frontend": FRONTEND_PORT}, timeout=30)

    if ready.get("Backend"):
        _backend_ready.set()  # stop suppressing proxy errors
        _status("Backend  ✓  http://127.0.0.1:" + str(BACKEND_PORT), GREEN)
    else:
        _status("WARNING: Backend not detected. Check log below for errors.", RED)

    if ready.get("Frontend"):
        _status("Frontend ✓  http://localhost:" + str(FRONTEND_PORT), GREEN)
    else:
        _status("WARNING: Frontend not detected. Run: cd frontend && npm install", YELLOW)

    # ── Open browser ──────────────────────────────────────────────────────
    if open_browser and ready.get("Frontend"):
        threading.Timer(0.5, webbrowser.open, args=[f"http://localhost:{FRONTEND_PORT}"]).start()

    # ── Stream backend log in main thread ─────────────────────────────────
    print(f"\n  {DIM}{'─' * 60}{RESET}")
    print(f"  {BOLD}Backend log{RESET}  {DIM}(Ctrl+C to stop){RESET}")
    print(f"  {DIM}{'─' * 60}{RESET}\n")

    try:
        # Keep main thread alive while backend runs
        while backend_thread.is_alive():
            backend_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()


def _shutdown():
    global _frontend_proc
    print(f"\n  {YELLOW}Shutting down...{RESET}")

    if _frontend_proc and _frontend_proc.poll() is None:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(_frontend_proc.pid)],
                    capture_output=True, timeout=5,
                )
            else:
                _frontend_proc.terminate()
                _frontend_proc.wait(timeout=5)
        except Exception:
            pass
        _frontend_proc = None

    _status("SimpliSolar stopped.", DIM)


if sys.platform == "win32":
    try:
        signal.signal(signal.SIGBREAK, lambda *_: _shutdown())
    except (OSError, ValueError):
        pass


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
