from __future__ import annotations

import argparse
import gc
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .domain import MarketBar
from .experts.chronos import Chronos2Expert
from .experts.kronos import KronosExpert
from .experts.sentiment import ModernFinBERTExpert


class ExpertHost:
    def __init__(self):
        self.loaded: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        self._lock = threading.RLock()
        self.device = self._detect_device()

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )
        except Exception:
            return "cpu"

    def _build(self, key: str):
        if key == "kronos":
            return KronosExpert(
                device=self.device,
            )
        if key == "chronos2":
            return Chronos2Expert(
                device_map=self.device,
            )
        if key == "finbert":
            return ModernFinBERTExpert(
                device=(
                    0
                    if self.device == "cuda"
                    else -1
                )
            )
        raise ValueError(f"unknown_expert:{key}")

    def load(self, key: str):
        key = str(key).strip().lower()
        with self._lock:
            existing = self.loaded.get(key)
            if existing is not None:
                return existing
            expert = self._build(key)
            try:
                loader = getattr(
                    expert,
                    "_load",
                    None,
                )
                if callable(loader):
                    loader()
                self.loaded[key] = expert
                self.errors.pop(key, None)
                return expert
            except Exception as exc:
                self.errors[key] = (
                    f"{type(exc).__name__}: {exc}"
                )
                raise

    def get_loaded(self, key: str):
        key = str(key).strip().lower()
        with self._lock:
            expert = self.loaded.get(key)
        if expert is None:
            raise RuntimeError(
                f"expert_not_loaded:{key}"
            )
        return expert

    def unload(self) -> None:
        with self._lock:
            self.loaded.clear()
            self.errors.clear()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def status(self) -> dict:
        with self._lock:
            return {
                "ok": True,
                "device": self.device,
                "loaded": sorted(self.loaded),
                "errors": dict(self.errors),
            }


def _bars(rows) -> list[MarketBar]:
    result = []
    for row in rows or []:
        result.append(
            MarketBar(
                ts=int(row["ts"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return result


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 11436,
) -> ThreadingHTTPServer:
    runtime = ExpertHost()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            del fmt, args

        def _json(self, status: int, payload: dict):
            raw = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header(
                "Content-Length",
                str(len(raw)),
            )
            self.end_headers()
            self.wfile.write(raw)

        def _read(self) -> dict:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
                or "0"
            )
            if length <= 0:
                return {}
            return json.loads(
                self.rfile.read(length).decode(
                    "utf-8"
                )
            )

        def do_GET(self):
            if self.path == "/health":
                self._json(
                    200,
                    {
                        "ok": True,
                        "device": runtime.device,
                    },
                )
                return
            if self.path == "/status":
                self._json(
                    200,
                    runtime.status(),
                )
                return
            self._json(
                404,
                {"error": "not_found"},
            )

        def do_POST(self):
            try:
                payload = self._read()
                if self.path == "/load":
                    experts = [
                        str(x).strip().lower()
                        for x in payload.get(
                            "experts",
                            [],
                        )
                    ]
                    loaded = []
                    errors = {}
                    for key in experts:
                        try:
                            runtime.load(key)
                            loaded.append(key)
                        except Exception as exc:
                            errors[key] = (
                                f"{type(exc).__name__}: {exc}"
                            )
                    self._json(
                        200,
                        {
                            **runtime.status(),
                            "requested": experts,
                            "loaded_now": loaded,
                            "load_errors": errors,
                        },
                    )
                    return

                if self.path == "/forecast":
                    key = str(
                        payload.get(
                            "expert",
                            "",
                        )
                    ).lower()
                    if key not in {
                        "kronos",
                        "chronos2",
                    }:
                        raise ValueError(
                            "forecast_expert_required"
                        )
                    expert = runtime.get_loaded(key)
                    result = expert.forecast(
                        str(payload["symbol"]),
                        _bars(payload["bars"]),
                        int(payload["horizon"]),
                    )
                    self._json(
                        200,
                        result.to_dict(),
                    )
                    return

                if self.path == "/sentiment":
                    expert = runtime.get_loaded(
                        "finbert"
                    )
                    result = expert.classify(
                        str(
                            payload.get(
                                "text",
                                "",
                            )
                        )
                    )
                    self._json(
                        200,
                        result.to_dict(),
                    )
                    return

                if self.path == "/unload":
                    runtime.unload()
                    self._json(
                        200,
                        runtime.status(),
                    )
                    return

                if self.path == "/shutdown":
                    self._json(
                        200,
                        {"ok": True},
                    )
                    threading.Thread(
                        target=self.server.shutdown,
                        daemon=True,
                    ).start()
                    return

                self._json(
                    404,
                    {"error": "not_found"},
                )
            except Exception as exc:
                self._json(
                    500,
                    {
                        "error": (
                            f"{type(exc).__name__}: "
                            f"{exc}"
                        )
                    },
                )

    server = ThreadingHTTPServer(
        (host, int(port)),
        Handler,
    )
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="caos-experts",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=11436,
    )
    args = parser.parse_args(argv)
    server = serve(
        host=args.host,
        port=args.port,
    )
    try:
        server.serve_forever(
            poll_interval=0.25,
        )
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
