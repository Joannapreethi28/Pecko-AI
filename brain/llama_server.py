"""Start/stop a llama-server process with the flags Brain needs (one slot, 1 decode thread)."""
import subprocess
import time
from pathlib import Path

from brain.llama_client import LlamaClient

DEFAULT_EXTRA: tuple = ()   # becomes ("-fa", "on") if the quantized V cache needs flash attention


def find_llama_server(root=Path("models/llama.cpp")) -> Path:
    root = Path(root)
    for name in ("llama-server.exe", "llama-server"):
        for p in sorted(root.rglob(name)):
            if p.is_file():
                return p
    raise FileNotFoundError(f"llama-server not found under {root}")


class LlamaServer:
    def __init__(self, model, *, ctx=2048, threads=1, threads_batch=2, port=8080, exe=None,
                 extra=DEFAULT_EXTRA, log_path=None):
        self.model, self.ctx, self.threads, self.threads_batch = Path(model), ctx, threads, threads_batch
        self.port, self.exe, self.extra = port, exe, tuple(extra)
        self.log_path = Path(log_path) if log_path else Path("data/results") / f"llama-server-{self.model.stem}.log"
        self._proc = None

    @property
    def pid(self):
        return self._proc.pid if self._proc else None

    def args(self) -> list:
        exe = self.exe or find_llama_server()
        return [str(exe), "-m", str(self.model), "-c", str(self.ctx), "-np", "1",
                "-t", str(self.threads), "-tb", str(self.threads_batch),
                "-ctk", "q8_0", "-ctv", "q8_0", "--host", "127.0.0.1", "--port", str(self.port),
                *self.extra]

    def start(self, timeout=120) -> float:
        t0 = time.monotonic()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "wb")
        try:
            self._proc = subprocess.Popen(self.args(), stdout=log, stderr=subprocess.STDOUT)
        finally:
            log.close()
        client = LlamaClient(port=self.port, timeout=2.0)
        while time.monotonic() - t0 < timeout:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-server exited with {self._proc.returncode}; see {self.log_path}")
            if client.health():
                return time.monotonic() - t0
            time.sleep(0.1)
        self.stop()
        raise TimeoutError(f"llama-server not healthy after {timeout}s; see {self.log_path}")

    def stop(self):
        p, self._proc = self._proc, None
        if p is None or p.poll() is not None:
            return
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
