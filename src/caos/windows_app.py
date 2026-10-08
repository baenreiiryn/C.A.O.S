from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
import threading
import webbrowser
from pathlib import Path
from types import SimpleNamespace

from .cli import build_caos
from .company.control import CompanyControlPort
from .company.dashboard import serve_company
from .company.domain import TraderMode
from .company.standalone import (
    build_daemon,
    build_policy,
    build_standalone_company,
    initialize_company,
    load_runtime_config,
    load_saved_policy,
    parse_scan_targets,
    require_initialized,
    save_runtime_config,
    targets_from_runtime_config,
)


WINDOWS_APP_VERSION = 1
DEFAULT_TARGETS = "BTCUSDT:long:momentum"
DEFAULT_DASHBOARD_PORT = 5191


class WindowsAppError(RuntimeError):
    pass


def app_data_dir(
    *,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    local = env.get("LOCALAPPDATA")
    if local:
        return Path(local) / "CAOS"
    base = home if home is not None else Path.home()
    return base / ".caos"


def default_launcher_config(
    *,
    data_dir: Path | None = None,
) -> dict:
    root = data_dir or app_data_dir()
    return {
        "version": WINDOWS_APP_VERSION,
        "provider": "static",
        "model": "qwen3:8b",
        "base_url": "",
        "company_capital": 10.0,
        "trader_bucket": 10.0,
        "stop_floor": 3.0,
        "default_max_exposure": 20.0,
        "operational_cap": 6,
        "company_max_dd": 30.0,
        "targets": DEFAULT_TARGETS,
        "interval": "60",
        "candle_limit": 500,
        "opportunity_ttl_ms": 3_600_000,
        "every_seconds": 60.0,
        "dashboard_port": DEFAULT_DASHBOARD_PORT,
        "state_db": str(root / "caos.db"),
    }


def launcher_config_path(
    *,
    data_dir: Path | None = None,
) -> Path:
    return (data_dir or app_data_dir()) / "launcher.json"


def load_launcher_config(
    *,
    data_dir: Path | None = None,
) -> dict | None:
    path = launcher_config_path(data_dir=data_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("version", 0)) != WINDOWS_APP_VERSION:
        raise WindowsAppError("unsupported_launcher_config")
    return validate_launcher_config(payload, data_dir=data_dir)


def save_launcher_config(
    config: dict,
    *,
    data_dir: Path | None = None,
) -> dict:
    validated = validate_launcher_config(
        config,
        data_dir=data_dir,
    )
    path = launcher_config_path(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            validated,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)
    return validated


def _float_between(
    value,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WindowsAppError(f"{name}_must_be_numeric") from exc
    if not minimum <= parsed <= maximum:
        raise WindowsAppError(
            f"{name}_must_be_between_{minimum:g}_and_{maximum:g}"
        )
    return parsed


def _int_between(
    value,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WindowsAppError(f"{name}_must_be_integer") from exc
    if not minimum <= parsed <= maximum:
        raise WindowsAppError(
            f"{name}_must_be_between_{minimum}_and_{maximum}"
        )
    return parsed


def validate_launcher_config(
    config: dict,
    *,
    data_dir: Path | None = None,
) -> dict:
    defaults = default_launcher_config(data_dir=data_dir)
    merged = {**defaults, **dict(config)}
    provider = str(merged["provider"]).strip().lower()
    if provider not in {
        "static",
        "ollama",
        "openai-compatible",
    }:
        raise WindowsAppError("unsupported_provider")

    targets = str(merged["targets"]).strip()
    if not targets:
        raise WindowsAppError("targets_required")
    try:
        parse_scan_targets(targets)
    except Exception as exc:
        raise WindowsAppError(
            f"invalid_targets:{exc}"
        ) from exc

    state_db = Path(str(merged["state_db"])).expanduser()
    if not state_db.is_absolute():
        state_db = (data_dir or app_data_dir()) / state_db

    validated = {
        "version": WINDOWS_APP_VERSION,
        "provider": provider,
        "model": str(merged["model"]).strip() or "qwen3:8b",
        "base_url": str(merged.get("base_url", "")).strip(),
        "company_capital": _float_between(
            merged["company_capital"],
            name="company_capital",
            minimum=1.0,
            maximum=1_000_000_000.0,
        ),
        "trader_bucket": _float_between(
            merged["trader_bucket"],
            name="trader_bucket",
            minimum=0.01,
            maximum=1_000_000_000.0,
        ),
        "stop_floor": _float_between(
            merged["stop_floor"],
            name="stop_floor",
            minimum=0.0,
            maximum=1_000_000_000.0,
        ),
        "default_max_exposure": _float_between(
            merged["default_max_exposure"],
            name="default_max_exposure",
            minimum=0.01,
            maximum=100.0,
        ),
        "operational_cap": _int_between(
            merged["operational_cap"],
            name="operational_cap",
            minimum=1,
            maximum=1024,
        ),
        "company_max_dd": _float_between(
            merged["company_max_dd"],
            name="company_max_dd",
            minimum=0.01,
            maximum=100.0,
        ),
        "targets": targets,
        "interval": str(merged["interval"]).strip() or "60",
        "candle_limit": _int_between(
            merged["candle_limit"],
            name="candle_limit",
            minimum=20,
            maximum=10_000,
        ),
        "opportunity_ttl_ms": _int_between(
            merged["opportunity_ttl_ms"],
            name="opportunity_ttl_ms",
            minimum=1_000,
            maximum=604_800_000,
        ),
        "every_seconds": _float_between(
            merged["every_seconds"],
            name="every_seconds",
            minimum=1.0,
            maximum=86_400.0,
        ),
        "dashboard_port": _int_between(
            merged["dashboard_port"],
            name="dashboard_port",
            minimum=1024,
            maximum=65_535,
        ),
        "state_db": str(state_db),
    }
    if validated["stop_floor"] > validated["trader_bucket"]:
        raise WindowsAppError(
            "stop_floor_cannot_exceed_trader_bucket"
        )
    if (
        validated["trader_bucket"]
        > validated["company_capital"]
    ):
        raise WindowsAppError(
            "trader_bucket_cannot_exceed_company_capital"
        )
    return validated


def _caos_args(config: dict) -> SimpleNamespace:
    return SimpleNamespace(
        provider=config["provider"],
        model=config["model"],
        base_url=config["base_url"] or None,
        experts="",
        news_feeds="",
        state_db=config["state_db"],
        restore=True,
        capital=config["company_capital"],
        max_dd=config["company_max_dd"],
        max_position=config["default_max_exposure"],
    )


def initialize_or_restore(config: dict):
    config = validate_launcher_config(config)
    caos = build_caos(_caos_args(config))
    policy = load_saved_policy(caos.store)
    if policy is None:
        policy = build_policy(
            initial_company_capital=config["company_capital"],
            trader_initial_bucket=config["trader_bucket"],
            trader_stop_floor=config["stop_floor"],
            default_trader_max_exposure_pct=(
                config["default_max_exposure"]
            ),
            operational_trader_cap=config["operational_cap"],
            company_max_drawdown_pct=config["company_max_dd"],
        )
        company, _ = build_standalone_company(
            caos,
            policy,
            restore=False,
        )
        targets = parse_scan_targets(config["targets"])
        initialize_company(
            company,
            targets,
            mode=TraderMode.PRODUCTION,
        )
        runtime = save_runtime_config(
            caos.store,
            targets,
            interval=config["interval"],
            candle_limit=config["candle_limit"],
            opportunity_ttl_ms=config["opportunity_ttl_ms"],
            every_seconds=config["every_seconds"],
        )
        return caos, company, targets, runtime, True

    company, restored = build_standalone_company(
        caos,
        policy,
        restore=True,
    )
    if not restored:
        raise WindowsAppError(
            "company_checkpoint_missing"
        )
    require_initialized(company)
    runtime = load_runtime_config(caos.store)
    if runtime is None:
        targets = parse_scan_targets(config["targets"])
        runtime = save_runtime_config(
            caos.store,
            targets,
            interval=config["interval"],
            candle_limit=config["candle_limit"],
            opportunity_ttl_ms=config["opportunity_ttl_ms"],
            every_seconds=config["every_seconds"],
        )
    else:
        targets = targets_from_runtime_config(runtime)
    return caos, company, targets, runtime, False


def port_available(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", int(port))) != 0
    finally:
        sock.close()


class CompanyRuntimeHost:
    def __init__(self, config: dict):
        self.config = validate_launcher_config(config)
        (
            self.caos,
            self.company,
            self.targets,
            self.runtime,
            self.initialized,
        ) = initialize_or_restore(self.config)
        self.control = CompanyControlPort(self.company)
        self.daemon = build_daemon(
            self.company,
            self.targets,
            interval=str(self.runtime.get("interval", "60")),
            candle_limit=int(
                self.runtime.get("candle_limit", 500)
            ),
            opportunity_ttl_ms=int(
                self.runtime.get(
                    "opportunity_ttl_ms",
                    3_600_000,
                )
            ),
        )
        self.stop_event = threading.Event()
        self.server = None
        self.daemon_thread = None
        self.server_thread = None

    @property
    def city_url(self) -> str:
        return (
            "http://127.0.0.1:"
            f"{self.config['dashboard_port']}"
        )

    def start(self) -> None:
        port = int(self.config["dashboard_port"])
        if not port_available(port):
            raise WindowsAppError(
                f"dashboard_port_{port}_already_in_use"
            )
        self.server = serve_company(
            self.control,
            host="127.0.0.1",
            port=port,
            open_browser=False,
        )
        self.daemon_thread = threading.Thread(
            target=self.daemon.serve,
            kwargs={
                "every_seconds": float(
                    self.runtime.get(
                        "every_seconds",
                        self.config["every_seconds"],
                    )
                ),
                "stop": self.stop_event.is_set,
            },
            name="caos-company-daemon",
            daemon=True,
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="caos-company-city",
            daemon=True,
        )
        self.daemon_thread.start()
        self.server_thread.start()

    def open_city(self) -> None:
        webbrowser.open(self.city_url)

    def stop(self) -> None:
        self.stop_event.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        try:
            if self.caos.store is not None:
                self.caos.store.close()
        except Exception:
            pass


def _wizard(config: dict) -> dict | None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("C.A.O.S — Founding Charter")
    root.geometry("720x720")
    root.minsize(660, 650)
    root.configure(bg="#15110d")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "CAOS.TFrame",
        background="#15110d",
    )
    style.configure(
        "CAOS.TLabel",
        background="#15110d",
        foreground="#ead8ad",
        font=("Segoe UI", 10),
    )
    style.configure(
        "Title.TLabel",
        background="#15110d",
        foreground="#f4d98b",
        font=("Segoe UI Semibold", 20),
    )
    style.configure(
        "CAOS.TButton",
        font=("Segoe UI Semibold", 10),
        padding=8,
    )

    outer = ttk.Frame(root, style="CAOS.TFrame", padding=24)
    outer.pack(fill="both", expand=True)
    ttk.Label(
        outer,
        text="Founding Charter",
        style="Title.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        outer,
        text=(
            "Configure the standalone Trade Company. "
            "LIVE trading remains unavailable."
        ),
        style="CAOS.TLabel",
    ).pack(anchor="w", pady=(4, 18))

    fields = [
        (
            "Company capital",
            "company_capital",
            str(config["company_capital"]),
        ),
        (
            "Initial Trader bucket",
            "trader_bucket",
            str(config["trader_bucket"]),
        ),
        (
            "Trader stop floor",
            "stop_floor",
            str(config["stop_floor"]),
        ),
        (
            "Default max exposure (%)",
            "default_max_exposure",
            str(config["default_max_exposure"]),
        ),
        (
            "Operational Trader cap",
            "operational_cap",
            str(config["operational_cap"]),
        ),
        (
            "Company max drawdown (%)",
            "company_max_dd",
            str(config["company_max_dd"]),
        ),
        (
            "Markets / targets",
            "targets",
            str(config["targets"]),
        ),
        (
            "Daemon cycle (seconds)",
            "every_seconds",
            str(config["every_seconds"]),
        ),
        (
            "City port",
            "dashboard_port",
            str(config["dashboard_port"]),
        ),
    ]
    variables: dict[str, tk.StringVar] = {}
    grid = ttk.Frame(outer, style="CAOS.TFrame")
    grid.pack(fill="x")
    for row, (label, key, value) in enumerate(fields):
        ttk.Label(
            grid,
            text=label,
            style="CAOS.TLabel",
        ).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 14),
            pady=5,
        )
        var = tk.StringVar(value=value)
        variables[key] = var
        entry = ttk.Entry(
            grid,
            textvariable=var,
            width=48,
        )
        entry.grid(
            row=row,
            column=1,
            sticky="ew",
            pady=5,
        )
    grid.columnconfigure(1, weight=1)

    provider_frame = ttk.Frame(
        outer,
        style="CAOS.TFrame",
    )
    provider_frame.pack(fill="x", pady=(16, 0))
    ttk.Label(
        provider_frame,
        text="Local AI provider",
        style="CAOS.TLabel",
    ).grid(row=0, column=0, sticky="w")
    provider = tk.StringVar(value=config["provider"])
    provider_box = ttk.Combobox(
        provider_frame,
        textvariable=provider,
        values=(
            "static",
            "ollama",
            "openai-compatible",
        ),
        state="readonly",
        width=24,
    )
    provider_box.grid(
        row=0,
        column=1,
        sticky="w",
        padx=(14, 0),
    )
    ttk.Label(
        provider_frame,
        text="Model",
        style="CAOS.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(8, 0))
    model = tk.StringVar(value=config["model"])
    ttk.Entry(
        provider_frame,
        textvariable=model,
        width=28,
    ).grid(
        row=1,
        column=1,
        sticky="w",
        padx=(14, 0),
        pady=(8, 0),
    )
    ttk.Label(
        provider_frame,
        text="Base URL (optional)",
        style="CAOS.TLabel",
    ).grid(row=2, column=0, sticky="w", pady=(8, 0))
    base_url = tk.StringVar(value=config["base_url"])
    ttk.Entry(
        provider_frame,
        textvariable=base_url,
        width=40,
    ).grid(
        row=2,
        column=1,
        sticky="w",
        padx=(14, 0),
        pady=(8, 0),
    )

    ttk.Label(
        outer,
        text=(
            "Target format: SYMBOL:direction:strategy. "
            "Example: BTCUSDT:long:momentum,ETHUSDT:long:trend"
        ),
        style="CAOS.TLabel",
        wraplength=640,
    ).pack(anchor="w", pady=(16, 4))
    ttk.Label(
        outer,
        text=(
            "Bybit TESTNET credentials are intentionally not stored "
            "by this wizard. Configure them later as environment "
            "variables when using the human-gated TESTNET tools."
        ),
        style="CAOS.TLabel",
        wraplength=640,
    ).pack(anchor="w", pady=(4, 16))

    result: dict[str, dict | None] = {"config": None}

    def submit() -> None:
        proposal = {
            **config,
            **{
                key: var.get()
                for key, var in variables.items()
            },
            "provider": provider.get(),
            "model": model.get(),
            "base_url": base_url.get(),
        }
        try:
            validated = validate_launcher_config(
                proposal
            )
        except Exception as exc:
            messagebox.showerror(
                "Invalid charter",
                str(exc),
                parent=root,
            )
            return
        result["config"] = validated
        root.destroy()

    buttons = ttk.Frame(outer, style="CAOS.TFrame")
    buttons.pack(fill="x", pady=(14, 0))
    ttk.Button(
        buttons,
        text="Found the Company",
        style="CAOS.TButton",
        command=submit,
    ).pack(side="right")
    ttk.Button(
        buttons,
        text="Cancel",
        style="CAOS.TButton",
        command=root.destroy,
    ).pack(side="right", padx=(0, 8))
    root.mainloop()
    return result["config"]


def _control_window(host: CompanyRuntimeHost) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("C.A.O.S Trade Company")
    root.geometry("430x250")
    root.resizable(False, False)
    root.configure(bg="#15110d")
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "CAOS.TFrame",
        background="#15110d",
    )
    style.configure(
        "CAOS.TLabel",
        background="#15110d",
        foreground="#ead8ad",
    )
    style.configure(
        "Title.TLabel",
        background="#15110d",
        foreground="#f4d98b",
        font=("Segoe UI Semibold", 16),
    )

    frame = ttk.Frame(
        root,
        style="CAOS.TFrame",
        padding=22,
    )
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text="C.A.O.S Trade Company",
        style="Title.TLabel",
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "The city and autonomous PAPER daemon are running."
        ),
        style="CAOS.TLabel",
    ).pack(anchor="w", pady=(6, 14))
    ttk.Label(
        frame,
        text=host.city_url,
        style="CAOS.TLabel",
    ).pack(anchor="w")

    button_row = ttk.Frame(frame, style="CAOS.TFrame")
    button_row.pack(fill="x", pady=(22, 0))
    ttk.Button(
        button_row,
        text="Open Arcane Trading City",
        command=host.open_city,
    ).pack(fill="x", pady=3)

    def stop() -> None:
        if messagebox.askyesno(
            "Stop Trade Company",
            (
                "Stop the local daemon and city server? "
                "State is already persisted."
            ),
            parent=root,
        ):
            host.stop()
            root.destroy()

    ttk.Button(
        button_row,
        text="Stop Trade Company",
        command=stop,
    ).pack(fill="x", pady=3)
    root.protocol("WM_DELETE_WINDOW", stop)
    root.after(250, host.open_city)
    root.mainloop()


def run_self_test() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        config = default_launcher_config(data_dir=root)
        config["state_db"] = str(root / "self-test.db")
        config["provider"] = "static"
        config["targets"] = "BTCUSDT:long:momentum"
        validated = validate_launcher_config(
            config,
            data_dir=root,
        )
        if validated["dashboard_port"] != 5191:
            return 2
        saved = save_launcher_config(
            validated,
            data_dir=root,
        )
        loaded = load_launcher_config(data_dir=root)
        if saved != loaded:
            return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="CAOS-Trade-Company",
        add_help=True,
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Open the setup wizard before launch.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    config = load_launcher_config(data_dir=data_dir)
    if config is None:
        config = default_launcher_config(data_dir=data_dir)
        state_db = Path(config["state_db"])
        if state_db.exists():
            try:
                from .store import Store

                store = Store(state_db)
                existing_policy = load_saved_policy(store)
                existing_runtime = load_runtime_config(store)
                store.close()
                if existing_policy is not None:
                    config.update(
                        {
                            "company_capital": (
                                existing_policy
                                .initial_company_capital
                            ),
                            "trader_bucket": (
                                existing_policy
                                .trader_initial_bucket
                            ),
                            "stop_floor": (
                                existing_policy
                                .trader_stop_floor
                            ),
                            "default_max_exposure": (
                                existing_policy
                                .default_trader_max_exposure_pct
                            ),
                            "operational_cap": (
                                existing_policy
                                .operational_trader_cap
                            ),
                            "company_max_dd": (
                                existing_policy
                                .company_max_drawdown_pct
                            ),
                        }
                    )
                if existing_runtime is not None:
                    config.update(
                        {
                            "targets": ",".join(
                                (
                                    f"{row['symbol']}:"
                                    f"{row.get('direction', 'long')}:"
                                    + "+".join(
                                        row.get(
                                            "strategy_candidates",
                                            [],
                                        )
                                    )
                                )
                                for row in existing_runtime.get(
                                    "targets",
                                    [],
                                )
                            )
                            or DEFAULT_TARGETS,
                            "interval": existing_runtime.get(
                                "interval",
                                "60",
                            ),
                            "candle_limit": existing_runtime.get(
                                "candle_limit",
                                500,
                            ),
                            "opportunity_ttl_ms": (
                                existing_runtime.get(
                                    "opportunity_ttl_ms",
                                    3_600_000,
                                )
                            ),
                            "every_seconds": (
                                existing_runtime.get(
                                    "every_seconds",
                                    60.0,
                                )
                            ),
                        }
                    )
            except Exception:
                pass

    if args.setup or not Path(config["state_db"]).exists():
        chosen = _wizard(config)
        if chosen is None:
            return 0
        config = save_launcher_config(
            chosen,
            data_dir=data_dir,
        )
    elif not launcher_config_path(
        data_dir=data_dir
    ).exists():
        config = save_launcher_config(
            config,
            data_dir=data_dir,
        )

    try:
        host = CompanyRuntimeHost(config)
        host.start()
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "C.A.O.S could not start",
            str(exc),
            parent=root,
        )
        root.destroy()
        return 1

    try:
        _control_window(host)
    finally:
        host.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
