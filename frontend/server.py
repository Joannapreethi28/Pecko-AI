"""A localhost-only presentation server, using Pecko's real intent router.

Run ``python -m frontend`` from the repository. This typed-text demonstration
does not run ASR, synthesize speech, or measure end-of-speech to first audio.
Only an already-running local llama-server is contacted; nothing is downloaded.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path, PurePosixPath
import socket
import threading
import time
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_BODY_BYTES = 16_384
MAX_TEXT_LENGTH = 1_000
INDIA_TIME = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
STATIC_FILES = {"index.html", "app.js", "styles.css", "favicon.svg", "evidence.json"}
ASSET_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf"}
DOCUMENT_DIRECTORIES = {"docs", "brain", "ears", "voice", "spine", "mobile"}


def safe_file(root: Path, relative: str) -> Path | None:
    """Resolve a file beneath root without following a symlink or junction."""
    if "\\" in relative or "\x00" in relative or ":" in relative:
        return None
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in {".", ".."} for p in parts):
        return None
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            return None
    try:
        candidate.resolve().relative_to(root.resolve())
        return candidate if candidate.is_file() else None
    except (ValueError, OSError):
        return None


def permitted_source(relative: str) -> bool:
    path = PurePosixPath(relative)
    if relative in {"README.md", "brain/router.py", "brain/llama_client.py", "brain/intents.yaml"}:
        return True
    if path.parts and path.parts[0] in DOCUMENT_DIRECTORIES and path.suffix == ".md":
        return True
    if path.parts[:2] == ("data", "results") and path.suffix in {".json", ".jsonl"}:
        return True
    if path.parts[:3] == ("data", "results", "voice_samples") and path.suffix == ".wav":
        return len(path.parts) == 4
    return path.parts[:2] == ("spine", "examples") and path.suffix == ".json"


class DemoRuntime:
    def __init__(self, root: Path = REPO_ROOT, model_family: str = "qwen3"):
        self.root = Path(root)
        self.model_family = model_family
        self.router = None
        self.router_error = None
        self.intent_text = {}
        self.model_lock = threading.Lock()
        try:
            import yaml
            from brain.router import Router
            intents_path = self.root / "brain" / "intents.yaml"
            self.router = Router.load(intents_path, clock=lambda: datetime.now(INDIA_TIME))
            document = yaml.safe_load(intents_path.read_text(encoding="utf-8"))
            self.intent_text = {intent["name"]: intent["say"] for intent in document["intents"]}
        except ImportError:
            self.router_error = "Install frontend/requirements.txt to enable the repository's intent router."
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            self.router_error = "The repository intent definitions could not be loaded."

    def model_available(self) -> bool:
        import http.client
        from brain.llama_client import LlamaClient
        try:
            return LlamaClient(host="127.0.0.1", port=8080, timeout=0.3).health()
        except (OSError, ValueError, http.client.HTTPException):
            return False

    def status(self) -> dict:
        return {
            "router": {"available": self.router is not None, "intents": len(self.intent_text),
                       "error": self.router_error},
            "llm": {"available": self.model_available(), "endpoint": "127.0.0.1:8080",
                    "family": self.model_family},
            "demo": {"mode": "typed-text", "audio": False, "timezone": "Asia/Kolkata",
                     "max_text_length": MAX_TEXT_LENGTH},
            "evidence": {"available": safe_file(self.root / "frontend", "evidence.json") is not None},
            "offline": True,
        }

    def chat(self, text: str) -> dict:
        from brain.prompt import normalize
        start = time.perf_counter()
        normalized = normalize(text)
        response = {"text": "", "route": "unavailable", "intent": None,
                    "source": "brain/router.py", "available": False,
                    "normalized_text": normalized, "match_score": None,
                    "mode": "typed-text", "audio": False}
        if self.router is None:
            response["text"] = self.router_error
        else:
            route = self.router.route(normalized)
            response.update(route=route.kind, intent=route.intent, match_score=route.score)
            if route.kind == "cached":
                response.update(text=self.intent_text[route.intent], available=True,
                                source="brain/intents.yaml", clip=route.clip)
            elif route.kind == "composed":
                response.update(text=route.text, available=True, source="brain/router.py")
            elif not self.model_available():
                response.update(text="This question needs the local language model. The model server is not running on this device; cached replies and the time and date are available.",
                                source="brain/llama_client.py", reason="model_unavailable")
            elif not self.model_lock.acquire(blocking=False):
                response.update(text="The local model is answering another question. Please try again shortly.",
                                source="brain/llama_client.py", reason="model_busy")
            else:
                try:
                    response.update(self.generate(text))
                finally:
                    self.model_lock.release()
        response["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
        response["timing_label"] = "Typed-text server response; not first-audio latency"
        return response

    def generate(self, text: str) -> dict:
        from brain.llama_client import LlamaClient, LlamaError
        from brain.prompt import PromptBuilder
        from brain.speakable import ThinkFilter, clean
        import http.client
        client = LlamaClient(host="127.0.0.1", port=8080, timeout=20)
        filter_thinking = ThinkFilter()
        parts = []
        stream = client.stream(PromptBuilder(self.model_family).final(text), n_predict=60)
        deadline = time.monotonic() + 45
        try:
            for piece in stream:
                if time.monotonic() > deadline:
                    raise TimeoutError("Local model response timed out")
                parts.append(filter_thinking.feed(piece.text))
            parts.append(filter_thinking.flush())
            answer = clean("".join(parts))
            if not answer:
                raise ValueError("The local model returned no answer")
            return {"text": answer, "available": True, "source": "brain/llama_client.py"}
        except (OSError, LlamaError, http.client.HTTPException, ValueError):
            return {"text": "The local model could not complete this reply. Try a cached prompt or check the model server.",
                    "available": False, "source": "brain/llama_client.py", "reason": "model_error"}
        finally:
            stream.close()


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "PeckoLocal/1.0"

    @property
    def runtime(self) -> DemoRuntime:
        return self.server.runtime

    def setup(self):
        super().setup()
        self.connection.settimeout(8)
        self.body_consumed = False

    def send_payload(self, status: int, payload: bytes, content_type: str, *, source=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if source:
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def json_response(self, status: int, value: dict):
        self.send_payload(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8")

    def send_error(self, code, message=None, explain=None):
        # Drain small rejected bodies so Windows does not discard the error
        # response when closing a socket that still contains unread data.
        if not self.body_consumed and hasattr(self, "headers"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= MAX_BODY_BYTES * 4:
                    self.connection.settimeout(0.2)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
        self.json_response(code, {"error": {"code": code, "message": message or "Request failed"}})
        self.close_connection = True

    def local_request(self) -> bool:
        port = self.server.server_address[1]
        hosts = {"127.0.0.1", "localhost", f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host", "").lower() not in hosts:
            self.send_error(403, "This presentation is available on localhost only")
            return False
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            self.send_error(403, "Cross-origin requests are not allowed")
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.local_request():
            return
        path = unquote(urlsplit(self.path).path)
        if path == "/api/status":
            self.json_response(200, self.runtime.status())
            return
        if path == "/api/evidence":
            evidence = safe_file(self.runtime.root / "frontend", "evidence.json")
            if evidence is None:
                self.send_error(503, "Repository evidence has not been generated")
                return
            try:
                self.json_response(200, json.loads(evidence.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                self.send_error(503, "Repository evidence could not be loaded")
            return
        source = path.startswith("/source/")
        if source:
            relative = path[len("/source/"):]
            file = safe_file(self.runtime.root, relative) if permitted_source(relative) else None
        else:
            relative = "index.html" if path == "/" else path.lstrip("/")
            allowed = relative in STATIC_FILES or (relative.startswith("assets/") and
                                                  PurePosixPath(relative).suffix in ASSET_EXTENSIONS)
            file = safe_file(self.runtime.root / "frontend", relative) if allowed else None
        if file is None:
            self.send_error(404, "File not found")
            return
        content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if source and file.suffix not in {".wav", ".json"}:
            content_type = "text/plain; charset=utf-8"
        elif file.suffix in {".js", ".css", ".html", ".json", ".svg"}:
            content_type += "; charset=utf-8"
        try:
            self.send_payload(200, file.read_bytes(), content_type, source=source)
        except OSError:
            self.send_error(404, "File not found")

    def do_POST(self):
        if not self.local_request():
            return
        if urlsplit(self.path).path != "/api/chat":
            self.send_error(404, "API endpoint not found")
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415, "Send an application/json request")
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Chunked request bodies are not supported")
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self.send_error(413 if length > MAX_BODY_BYTES else 400, "Invalid request body length")
            return
        try:
            self.body_consumed = True
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, socket.timeout):
            self.send_error(400, "Send valid JSON containing a text field")
            return
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            self.send_error(400, "The text field must be a string")
            return
        text = body["text"].strip()
        if not text or len(text) > MAX_TEXT_LENGTH:
            self.send_error(400, f"Enter between 1 and {MAX_TEXT_LENGTH} characters")
            return
        self.json_response(200, self.runtime.chat(text))

    def log_message(self, format, *args):
        # Avoid printing user questions. Request paths contain no chat content.
        print(f"[presentation] {format % args}")


def make_server(port: int = 8765, runtime: DemoRuntime | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    server.daemon_threads = True
    server.runtime = runtime or DemoRuntime()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model-family", choices=("qwen3", "lfm2"), default="qwen3",
                        help="Prompt format of the already-running local model")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    server = make_server(args.port, DemoRuntime(model_family=args.model_family))
    print(f"Pecko evaluator presentation: http://127.0.0.1:{args.port}")
    print("Typed-text router demo and recorded evidence. No microphone or live speech pipeline.")
    if server.runtime.router_error:
        print(server.runtime.router_error)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
