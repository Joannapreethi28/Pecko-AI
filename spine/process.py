"""Own one engine process, its logs, bounded readiness and exit notification.

Children inherit the parent's cgroup on Linux. Launch this supervisor INSIDE
pecko.scope. Executable and model arguments come from the engine owner.
"""

import os
from pathlib import Path
import subprocess
import math
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

from common.clock import now


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_health_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1")
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment):
        raise ValueError("Health checks require HTTP on literal loopback, without credentials/fragment")
    # Accessing port validates malformed/out-of-range values.
    parsed.port


def health_ready(url: str, timeout: float) -> bool:
    validate_health_url(url)
    # No environment proxies, redirects or external DNS. Only the explicit
    # loopback endpoint may be contacted, even if it redirects elsewhere.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(Request(url, method="GET"), timeout=timeout) as response:
            return response.status == 200
    except (OSError, HTTPError, URLError):
        return False


class EngineProcess:
    def __init__(self, argv: list[str], log_path: Path, on_failure,
                 *, cwd: Path | None = None, env: dict | None = None):
        if not argv or any(not isinstance(arg, str) or not arg for arg in argv):
            raise ValueError("Expected a nonempty argument list")
        self.argv = list(argv)
        self.log_path, self.on_failure = log_path, on_failure
        self.cwd, self.env = cwd, env or {}
        self.process = None
        self._stream = None
        self._watcher = None
        self._stopping = Event()
        self._used = False

    def start(self, *, health_url: str | None = None, readiness_timeout_s: float = 30) -> None:
        """Launch and optionally wait for readiness. Stage still owns warm-up."""
        if self._used:
            raise RuntimeError("Create a fresh supervisor for each engine launch")
        if health_url is not None:
            validate_health_url(health_url)
            if not math.isfinite(readiness_timeout_s) or readiness_timeout_s <= 0:
                raise ValueError("Readiness timeout must be positive and finite")
            if health_ready(health_url, 0.2):
                raise RuntimeError("Health endpoint already serves another process; use a dedicated port")
        self._used = True
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve engine logs just as experiment evidence is preserved.
        self._stream = self.log_path.open("xb")
        env = dict(os.environ, **self.env)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL,
                                            stdout=self._stream, stderr=subprocess.STDOUT,
                                            cwd=self.cwd, env=env, shell=False,
                                            creationflags=flags)
        except BaseException:
            self._stream.close()
            raise
        self._watcher = Thread(target=self._watch, name="pecko-engine-exit", daemon=True)
        self._watcher.start()
        if health_url is not None:
            self.wait_ready(health_url, readiness_timeout_s)

    def _watch(self):
        code = self.process.wait()
        if not self._stopping.is_set():
            self.on_failure(f"Engine exited unexpectedly with code {code}; see {self.log_path}")

    def wait_ready(self, health_url: str, timeout_s: float = 30) -> None:
        """Startup-only health wait, never used for first-audio dispatch.

        Call on the stage's startup path. This checks HTTP readiness only; the
        stage must perform its own warm-up and contract/model compatibility check.
        """
        validate_health_url(health_url)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("Readiness timeout must be positive and finite")
        if self.process is None:
            raise RuntimeError("Launch engine before waiting for readiness")
        deadline = now() + timeout_s
        try:
            while True:
                code = self.process.poll()
                if code is not None:
                    raise RuntimeError(f"Engine exited before readiness with code {code}")
                remaining = deadline - now()
                if remaining <= 0:
                    raise TimeoutError("Engine readiness deadline exceeded")
                if health_ready(health_url, min(0.2, remaining)):
                    if self.process.poll() is not None:
                        raise RuntimeError("Engine exited during readiness check")
                    return
                self._stopping.wait(min(0.05, max(0, deadline - now())))
                if self._stopping.is_set():
                    raise RuntimeError("Engine stopped during readiness wait")
        except BaseException:
            self.stop()
            raise

    def stop(self, grace_s: float = 2) -> None:
        """Terminate, then kill if needed; watcher and output stream are closed."""
        if not math.isfinite(grace_s) or grace_s < 0:
            raise ValueError("grace_s must be nonnegative and finite")
        self._stopping.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self._watcher is not None:
            self._watcher.join(timeout=2)
            if self._watcher.is_alive():
                raise RuntimeError("Engine exit watcher did not stop")
        if self._stream is not None:
            self._stream.close()
