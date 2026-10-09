from __future__ import annotations

import ctypes
import json
import os
import re
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import uuid4

from .llm import OllamaClient, OpenAICompatClient, StaticLLM
from .execution_reliability import DurableExecutionJournal
from .news import (
    NewsAnalyzer,
    RSSNewsClient,
    default_news_sources,
    normalize_news_sources,
)
from .testnet import BinanceSpotClient


SETTINGS_API_VERSION = "settings/v1"
SUPPORTED_BROKERS = {
    "binance": {
        "label": "Binance Japan / Spot",
        "environments": (
            "spot-testnet",
            "production-readonly",
            "production-manual",
        ),
        "activatable": True,
        "execution_environment": "spot-testnet",
        "notes": (
            "Spot TESTNET can run autonomously after the operator selects "
            "TESTNET mode. Production-manual creates real order proposals "
            "but requires an explicit human confirmation for every order."
        ),
    },
}


class SettingsError(RuntimeError):
    pass


class CredentialVault(Protocol):
    def set(self, key: str, secret: str) -> None: ...
    def get(self, key: str) -> str | None: ...
    def delete(self, key: str) -> None: ...


class MemoryCredentialVault:
    """Test-only/non-persistent credential vault."""

    def __init__(self):
        self.values: dict[str, str] = {}

    def set(self, key: str, secret: str) -> None:
        self.values[str(key)] = str(secret)

    def get(self, key: str) -> str | None:
        return self.values.get(str(key))

    def delete(self, key: str) -> None:
        self.values.pop(str(key), None)


class WindowsCredentialVault:
    """Windows Credential Manager generic-credential wrapper."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    def __init__(self, namespace: str = "CAOS"):
        if os.name != "nt":
            raise SettingsError(
                "windows_credential_manager_unavailable"
            )
        self.namespace = namespace.strip() or "CAOS"
        self.advapi32 = ctypes.WinDLL(
            "Advapi32.dll",
            use_last_error=True,
        )
        self.advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(self.CREDENTIALW),
            wintypes.DWORD,
        ]
        self.advapi32.CredWriteW.restype = wintypes.BOOL
        self.advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(
                ctypes.POINTER(self.CREDENTIALW)
            ),
        ]
        self.advapi32.CredReadW.restype = wintypes.BOOL
        self.advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.advapi32.CredDeleteW.restype = wintypes.BOOL
        self.advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self.advapi32.CredFree.restype = None

    def _target(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def set(self, key: str, secret: str) -> None:
        target = self._target(key)
        encoded = str(secret).encode("utf-16-le")
        if len(encoded) > 2560:
            raise SettingsError("credential_too_large")
        blob = (
            (ctypes.c_ubyte * len(encoded)).from_buffer_copy(
                encoded
            )
            if encoded
            else None
        )
        credential = self.CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = (
            ctypes.cast(
                blob,
                ctypes.POINTER(ctypes.c_ubyte),
            )
            if blob is not None
            else None
        )
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "C.A.O.S"
        if not self.advapi32.CredWriteW(
            ctypes.byref(credential),
            0,
        ):
            raise SettingsError(
                f"credential_write_failed:{ctypes.get_last_error()}"
            )

    def get(self, key: str) -> str | None:
        pointer = ctypes.POINTER(self.CREDENTIALW)()
        ok = self.advapi32.CredReadW(
            self._target(key),
            self.CRED_TYPE_GENERIC,
            0,
            ctypes.byref(pointer),
        )
        if not ok:
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                return None
            raise SettingsError(
                f"credential_read_failed:{error}"
            )
        try:
            credential = pointer.contents
            size = int(credential.CredentialBlobSize)
            if size <= 0 or not credential.CredentialBlob:
                return ""
            raw = ctypes.string_at(
                credential.CredentialBlob,
                size,
            )
            return raw.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def delete(self, key: str) -> None:
        ok = self.advapi32.CredDeleteW(
            self._target(key),
            self.CRED_TYPE_GENERIC,
            0,
        )
        if not ok:
            error = ctypes.get_last_error()
            if error != 1168:
                raise SettingsError(
                    f"credential_delete_failed:{error}"
                )


def _json_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> dict:
    request = urllib.request.Request(
        url,
        headers=headers or {},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        raise SettingsError(
            f"connection_failed:{exc}"
        ) from exc


def _ollama_model_alias(value: str) -> str:
    name = str(value).strip()
    return (
        name[:-7]
        if name.lower().endswith(":latest")
        else name
    )


def _match_ollama_model(
    requested: str,
    discovered: list[str],
) -> str | None:
    requested = str(requested).strip()
    if not requested:
        return None
    if requested in discovered:
        return requested
    requested_alias = _ollama_model_alias(requested)
    for model in discovered:
        if _ollama_model_alias(model) == requested_alias:
            return model
    return None


def _clean_profile_id(value: str) -> str:
    cleaned = re.sub(
        r"[^a-zA-Z0-9_.-]+",
        "-",
        str(value).strip(),
    ).strip("-")
    return cleaned[:80]


@dataclass(slots=True)
class RuntimeSettingsService:
    caos: object
    company: object
    config: dict
    persist_config: Callable[[dict], dict]
    vault: CredentialVault
    ollama_runtime: object | None = None
    market_runtime: object | None = None
    update_runtime: object | None = None
    expert_runtime: object | None = None

    def __post_init__(self) -> None:
        """Drop legacy unsupported broker profiles from runtime metadata.

        Secrets are not deleted from the OS vault automatically; only the
        old profile metadata is removed from launcher configuration.
        """
        raw = self.config.get("broker_profiles", [])
        kept = [
            dict(row)
            for row in raw
            if (
                isinstance(row, dict)
                and str(
                    row.get("provider", "")
                ).lower()
                in SUPPORTED_BROKERS
            )
        ]
        active = self.config.get(
            "active_broker_profile"
        )
        known_ids = {
            str(row.get("id", ""))
            for row in kept
        }
        if active not in known_ids:
            active = None
        if kept != raw or active != self.config.get(
            "active_broker_profile"
        ):
            self._save_config(
                {
                    "broker_profiles": kept,
                    "active_broker_profile": active,
                }
            )

    def _llm_key(self) -> str:
        return "llm:openai-compatible:api_key"

    def _broker_key(
        self,
        profile_id: str,
        field: str,
    ) -> str:
        return f"broker:{profile_id}:{field}"

    def _profiles(self) -> list[dict]:
        rows = self.config.get("broker_profiles", [])
        if not isinstance(rows, list):
            return []
        return [
            dict(row)
            for row in rows
            if (
                isinstance(row, dict)
                and str(
                    row.get("provider", "")
                ).lower()
                in SUPPORTED_BROKERS
            )
        ]

    def _news_sources(self) -> list[dict]:
        raw = self.config.get(
            "news_sources",
            default_news_sources(),
        )
        try:
            return normalize_news_sources(raw)
        except ValueError:
            return default_news_sources()

    def _apply_news_sources(
        self,
        sources: list[dict],
    ) -> None:
        enabled = [
            row["url"]
            for row in sources
            if row.get("enabled", True)
        ]
        self.caos.news_analyzer = (
            NewsAnalyzer(
                RSSNewsClient(enabled),
                sentiment_expert=getattr(
                    self.caos,
                    "sentiment_expert",
                    None,
                ),
            )
            if enabled
            else None
        )

    def _save_config(self, updates: dict) -> dict:
        proposal = {**self.config, **updates}
        saved = self.persist_config(proposal)
        self.config.clear()
        self.config.update(saved)
        return saved

    def get_settings(self) -> dict:
        profiles = []
        for row in self._profiles():
            profile_id = str(row.get("id", ""))
            profiles.append(
                {
                    **row,
                    "api_key_configured": bool(
                        self.vault.get(
                            self._broker_key(
                                profile_id,
                                "api_key",
                            )
                        )
                    ),
                    "api_secret_configured": bool(
                        self.vault.get(
                            self._broker_key(
                                profile_id,
                                "api_secret",
                            )
                        )
                    ),
                }
            )
        policy_obj = getattr(
            self.company,
            "policy",
            None,
        )
        policy = (
            policy_obj.to_dict()
            if policy_obj is not None
            and hasattr(policy_obj, "to_dict")
            else {
                "trader_initial_bucket": self.config.get(
                    "trader_bucket",
                    10.0,
                ),
                "trader_stop_floor": self.config.get(
                    "stop_floor",
                    3.0,
                ),
                "default_trader_max_exposure_pct": (
                    self.config.get(
                        "default_max_exposure",
                        20.0,
                    )
                ),
                "company_max_drawdown_pct": self.config.get(
                    "company_max_dd",
                    30.0,
                ),
            }
        )
        operational_state_fn = getattr(
            self.company,
            "operational_state",
            None,
        )
        return {
            "version": SETTINGS_API_VERSION,
            "company": {
                "trader_initial_bucket": policy[
                    "trader_initial_bucket"
                ],
                "trader_stop_floor": policy[
                    "trader_stop_floor"
                ],
                "default_trader_max_exposure_pct": policy[
                    "default_trader_max_exposure_pct"
                ],
                "company_max_drawdown_pct": policy[
                    "company_max_drawdown_pct"
                ],
                "operational_state": (
                    operational_state_fn()
                    if callable(operational_state_fn)
                    else "unknown"
                ),
                "note": (
                    "Initial bucket and default exposure apply "
                    "to newly funded Traders; stop floor and "
                    "Company drawdown apply immediately after save."
                ),
            },
            "llm": {
                "provider": self.config.get(
                    "provider",
                    "static",
                ),
                "model": self.config.get(
                    "model",
                    "qwen3:8b",
                ),
                "base_url": self.config.get(
                    "base_url",
                    "",
                ),
                "api_key_configured": bool(
                    self.vault.get(self._llm_key())
                ),
            },
            "ollama_runtime": self.ollama_status(),
            "experts": (
                self.expert_runtime.status()
                if self.expert_runtime is not None
                else {
                    "enabled": False,
                    "installed": False,
                    "running": False,
                    "configured": [],
                    "loaded": [],
                    "errors": {},
                    "device": None,
                    "catalog": {},
                }
            ),
            "updates": (
                self.update_runtime.status()
                if self.update_runtime is not None
                else {
                    "enabled": False,
                    "current_version": None,
                    "update_available": False,
                    "checking": False,
                    "downloaded": False,
                    "install_supported": False,
                    "install_blockers": [],
                    "can_install": False,
                    "last_error": None,
                }
            ),
            "market_selection": (
                self.market_runtime.market_selection_status()
                if self.market_runtime is not None
                else {
                    "mode": self.config.get(
                        "market_selection_mode",
                        "manual",
                    ),
                    "auto_scan_every_seconds": self.config.get(
                        "auto_scan_every_seconds",
                        300.0,
                    ),
                    "autonomy": {
                        "timeframes": [
                            "1m",
                            "5m",
                            "15m",
                            "1h",
                        ],
                        "candidate_limit": self.config.get(
                            "auto_candidate_limit",
                            10,
                        ),
                        "latest_rankings": [],
                    },
                }
            ),
            "brokers": {
                "supported": SUPPORTED_BROKERS,
                "profiles": profiles,
                "active_profile_id": self.config.get(
                    "active_broker_profile"
                ),
            },
            "news": {
                "sources": self._news_sources(),
                "defaults": default_news_sources(),
                "enabled_count": sum(
                    1
                    for row in self._news_sources()
                    if row.get("enabled", True)
                ),
                "analyzer_active": (
                    getattr(
                        self.caos,
                        "news_analyzer",
                        None,
                    )
                    is not None
                ),
            },
        }

    def ollama_status(self) -> dict:
        if self.ollama_runtime is None:
            return {
                "enabled": False,
                "installed": False,
                "running": False,
                "managed_process": False,
                "base_url": "",
                "runtime_dir": "",
                "models_dir": "",
                "version": None,
            }
        return {
            "enabled": True,
            **self.ollama_runtime.status(),
        }

    def start_managed_ollama(self) -> dict:
        if self.ollama_runtime is None:
            raise SettingsError(
                "managed_ollama_unavailable"
            )
        return {
            "enabled": True,
            **self.ollama_runtime.start(),
        }

    def stop_managed_ollama(self) -> dict:
        if self.ollama_runtime is None:
            raise SettingsError(
                "managed_ollama_unavailable"
            )
        return {
            "enabled": True,
            **self.ollama_runtime.stop(),
        }

    def pick_managed_ollama_model(self) -> dict:
        if self.ollama_runtime is None:
            raise SettingsError(
                "managed_ollama_unavailable"
            )
        return self.ollama_runtime.pick_model_file()

    def import_managed_ollama_model(
        self,
        *,
        source_path: str,
        model_name: str = "",
    ) -> dict:
        if self.ollama_runtime is None:
            raise SettingsError(
                "managed_ollama_unavailable"
            )
        imported = self.ollama_runtime.import_gguf(
            source_path,
            model_name=model_name,
        )
        llm = self.save_llm(
            provider="ollama",
            model=str(imported["model"]),
            base_url=str(imported["base_url"]),
        )
        return {
            "imported": imported,
            "llm": llm,
            "ollama_runtime": self.ollama_status(),
        }

    def install_expert_runtime(self) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            return self.expert_runtime.install()
        except Exception as exc:
            raise SettingsError(str(exc)) from exc

    def start_expert_runtime(self) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            return self.expert_runtime.start()
        except Exception as exc:
            raise SettingsError(str(exc)) from exc

    def stop_expert_runtime(self) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            return self.expert_runtime.stop()
        except Exception as exc:
            raise SettingsError(str(exc)) from exc

    def load_enabled_experts(self) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            return self.expert_runtime.load_enabled()
        except Exception as exc:
            raise SettingsError(str(exc)) from exc

    def unload_experts(self) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            return self.expert_runtime.unload()
        except Exception as exc:
            raise SettingsError(str(exc)) from exc

    def save_experts(
        self,
        enabled,
    ) -> dict:
        if self.expert_runtime is None:
            raise SettingsError(
                "expert_runtime_unavailable"
            )
        try:
            status = self.expert_runtime.configure(
                list(enabled or [])
            )
        except Exception as exc:
            raise SettingsError(str(exc)) from exc
        self._save_config(
            {
                "experts_enabled": list(
                    status.get(
                        "configured",
                        [],
                    )
                )
            }
        )
        return status

    def discover_models(
        self,
        *,
        provider: str,
        base_url: str = "",
        api_key: str | None = None,
    ) -> dict:
        provider = str(provider).strip().lower()
        if provider == "static":
            return {
                "provider": "static",
                "models": ["static"],
            }
        if provider == "ollama":
            root = (
                base_url.strip()
                or (
                    self.ollama_runtime.base_url
                    if self.ollama_runtime is not None
                    else "http://127.0.0.1:11434"
                )
            ).rstrip("/")
            result = _json_get(root + "/api/tags")
            models = []
            for row in result.get("models", []) or []:
                name = row.get("name") or row.get("model")
                if name:
                    models.append(str(name))
            return {
                "provider": provider,
                "models": sorted(set(models)),
            }
        if provider == "openai-compatible":
            root = (
                base_url.strip()
                or "http://127.0.0.1:1234/v1"
            ).rstrip("/")
            key = (
                api_key
                or self.vault.get(self._llm_key())
                or "local"
            )
            result = _json_get(
                root + "/models",
                headers={
                    "Authorization": f"Bearer {key}"
                },
            )
            models = []
            for row in result.get("data", []) or []:
                if row.get("id"):
                    models.append(str(row["id"]))
            return {
                "provider": provider,
                "models": sorted(set(models)),
            }
        raise SettingsError("unsupported_llm_provider")

    def test_llm(
        self,
        *,
        provider: str,
        model: str,
        base_url: str = "",
        api_key: str | None = None,
    ) -> dict:
        discovered = self.discover_models(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
        )
        requested = str(model).strip()
        matched_model = requested
        if (
            provider == "ollama"
            and requested
            and discovered["models"]
        ):
            matched_model = _match_ollama_model(
                requested,
                discovered["models"],
            )
            if matched_model is None:
                return {
                    **discovered,
                    "ok": False,
                    "matched_model": None,
                    "message": (
                        f"Model {requested!r} was not returned "
                        "by the provider."
                    ),
                }
        elif (
            provider != "static"
            and requested
            and discovered["models"]
            and requested not in discovered["models"]
        ):
            return {
                **discovered,
                "ok": False,
                "matched_model": None,
                "message": (
                    f"Model {requested!r} was not returned "
                    "by the provider."
                ),
            }
        return {
            **discovered,
            "ok": True,
            "matched_model": matched_model or requested,
            "message": "Connection succeeded.",
        }

    def save_llm(
        self,
        *,
        provider: str,
        model: str,
        base_url: str = "",
        api_key: str | None = None,
        clear_api_key: bool = False,
    ) -> dict:
        provider = str(provider).strip().lower()
        model = str(model).strip()
        base_url = str(base_url).strip()
        if provider not in {
            "static",
            "ollama",
            "openai-compatible",
        }:
            raise SettingsError("unsupported_llm_provider")
        if not model:
            model = "static" if provider == "static" else "qwen3:8b"

        if clear_api_key:
            self.vault.delete(self._llm_key())
        elif api_key is not None and str(api_key):
            self.vault.set(
                self._llm_key(),
                str(api_key),
            )

        if provider == "ollama":
            effective_base_url = (
                base_url
                or (
                    self.ollama_runtime.base_url
                    if self.ollama_runtime is not None
                    else "http://127.0.0.1:11434"
                )
            )
            llm = OllamaClient(
                model,
                effective_base_url,
            )
            base_url = effective_base_url
        elif provider == "openai-compatible":
            llm = OpenAICompatClient(
                model,
                base_url
                or "http://127.0.0.1:1234/v1",
                self.vault.get(self._llm_key()) or "local",
            )
        else:
            llm = StaticLLM(
                '{"tool":"status","args":{}}'
            )
        self.caos.llm = llm
        self._save_config(
            {
                "provider": provider,
                "model": model,
                "base_url": base_url,
            }
        )
        return self.get_settings()["llm"]

    def save_market_selection(
        self,
        *,
        mode: str,
    ) -> dict:
        normalized = str(mode).strip().lower()
        if normalized not in {"auto", "manual"}:
            raise SettingsError(
                "market_selection_mode_must_be_auto_or_manual"
            )
        if self.market_runtime is None:
            raise SettingsError(
                "market_runtime_unavailable"
            )
        try:
            status = (
                self.market_runtime.configure_market_selection(
                    mode=normalized
                )
            )
        except Exception as exc:
            raise SettingsError(str(exc)) from exc
        self._save_config(
            {
                "market_selection_mode": normalized,
            }
        )
        return status

    def save_company_policy(
        self,
        *,
        trader_initial_bucket: float,
        trader_stop_floor: float,
        default_trader_max_exposure_pct: float,
        company_max_drawdown_pct: float,
    ) -> dict:
        updated = self.company.update_policy(
            trader_initial_bucket=float(
                trader_initial_bucket
            ),
            trader_stop_floor=float(
                trader_stop_floor
            ),
            default_trader_max_exposure_pct=float(
                default_trader_max_exposure_pct
            ),
            company_max_drawdown_pct=float(
                company_max_drawdown_pct
            ),
        )
        self._save_config(
            {
                "trader_bucket": updated[
                    "trader_initial_bucket"
                ],
                "stop_floor": updated[
                    "trader_stop_floor"
                ],
                "default_max_exposure": updated[
                    "default_trader_max_exposure_pct"
                ],
                "company_max_dd": updated[
                    "company_max_drawdown_pct"
                ],
            }
        )
        return self.get_settings()["company"]

    def save_news_sources(
        self,
        sources,
    ) -> dict:
        try:
            normalized = normalize_news_sources(
                list(sources or [])
            )
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
        self._apply_news_sources(normalized)
        self._save_config(
            {"news_sources": normalized}
        )
        return self.get_settings()["news"]

    def restore_default_news_sources(self) -> dict:
        return self.save_news_sources(
            default_news_sources()
        )

    def discover_news_feed(
        self,
        url: str,
    ) -> dict:
        try:
            return RSSNewsClient([]).discover_feed(
                str(url)
            )
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc

    def test_news_source(
        self,
        url: str,
    ) -> dict:
        try:
            return RSSNewsClient([]).test_feed(
                str(url)
            )
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc

    def preview_news(
        self,
        *,
        limit: int = 20,
        query: str | None = None,
    ) -> dict:
        analyzer = getattr(
            self.caos,
            "news_analyzer",
            None,
        )
        if analyzer is None:
            return {
                "items": [],
                "count": 0,
                "aggregate_sentiment": None,
                "errors": [],
            }
        return analyzer.latest(
            limit=max(1, min(int(limit), 100)),
            query=query,
            with_sentiment=True,
        )

    def save_broker_profile(
        self,
        *,
        profile_id: str | None,
        label: str,
        provider: str,
        environment: str,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> dict:
        provider = str(provider).strip().lower()
        if provider not in SUPPORTED_BROKERS:
            raise SettingsError("unsupported_broker")
        environment = str(environment).strip().lower()
        allowed = SUPPORTED_BROKERS[provider][
            "environments"
        ]
        if environment not in allowed:
            raise SettingsError("unsupported_broker_environment")

        profile_id = _clean_profile_id(
            profile_id
            or f"{provider}-{environment}-{uuid4().hex[:8]}"
        )
        if not profile_id:
            raise SettingsError("invalid_broker_profile_id")
        label = str(label).strip() or (
            f"{SUPPORTED_BROKERS[provider]['label']} "
            f"{environment.upper()}"
        )

        profiles = self._profiles()
        replacement = {
            "id": profile_id,
            "label": label,
            "provider": provider,
            "environment": environment,
        }
        found = False
        for index, row in enumerate(profiles):
            if str(row.get("id")) == profile_id:
                profiles[index] = replacement
                found = True
                break
        if not found:
            profiles.append(replacement)

        if api_key is not None and str(api_key):
            self.vault.set(
                self._broker_key(profile_id, "api_key"),
                str(api_key),
            )
        if api_secret is not None and str(api_secret):
            self.vault.set(
                self._broker_key(
                    profile_id,
                    "api_secret",
                ),
                str(api_secret),
            )
        self._save_config({"broker_profiles": profiles})
        return next(
            row
            for row in self.get_settings()["brokers"][
                "profiles"
            ]
            if row["id"] == profile_id
        )

    def delete_broker_profile(
        self,
        profile_id: str,
    ) -> dict:
        profile_id = str(profile_id)
        if (
            self.config.get("active_broker_profile")
            == profile_id
        ):
            raise SettingsError(
                "cannot_delete_active_broker_profile"
            )
        profiles = [
            row
            for row in self._profiles()
            if str(row.get("id")) != profile_id
        ]
        self.vault.delete(
            self._broker_key(profile_id, "api_key")
        )
        self.vault.delete(
            self._broker_key(profile_id, "api_secret")
        )
        self._save_config({"broker_profiles": profiles})
        return self.get_settings()["brokers"]

    def _profile(self, profile_id: str) -> dict:
        for row in self._profiles():
            if str(row.get("id")) == str(profile_id):
                return row
        raise SettingsError("unknown_broker_profile")

    def test_broker(
        self,
        profile_id: str,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> dict:
        profile = self._profile(profile_id)
        provider = profile["provider"]
        environment = profile["environment"]
        key = (
            api_key
            or self.vault.get(
                self._broker_key(profile_id, "api_key")
            )
        )
        secret = (
            api_secret
            or self.vault.get(
                self._broker_key(
                    profile_id,
                    "api_secret",
                )
            )
        )
        if not key or not secret:
            raise SettingsError(
                "broker_credentials_required"
            )
        if provider != "binance":
            raise SettingsError(
                "broker_adapter_not_implemented"
            )
        client = BinanceSpotClient(
            api_key=key,
            api_secret=secret,
            environment=environment,
        )
        info = client.get_account_info()
        return {
            "ok": True,
            "profile_id": profile_id,
            "provider": provider,
            "environment": environment,
            "can_trade": info.get("can_trade"),
            "permissions": info.get("permissions", []),
            "account_type": info.get("account_type"),
            "balances_nonzero": len(
                info.get("balances_nonzero", [])
            ),
            "production_execution_enabled": (
                environment == "production-manual"
            ),
            "production_execution_requires_confirmation": (
                environment == "production-manual"
            ),
            "message": (
                "Binance credentials authenticated. "
                + (
                    "Spot TESTNET adapter is available."
                    if environment == "spot-testnet"
                    else (
                        "Production account is connected for manual per-order confirmation."
                        if environment == "production-manual"
                        else "Production account is connected read-only."
                    )
                )
            ),
        }

    def set_active_broker(
        self,
        profile_id: str | None,
    ) -> dict:
        if profile_id in {None, ""}:
            self._save_config(
                {"active_broker_profile": None}
            )
            return self.get_settings()["brokers"]

        profile = self._profile(str(profile_id))
        metadata = SUPPORTED_BROKERS[
            profile["provider"]
        ]
        if not metadata["activatable"]:
            raise SettingsError(
                "broker_adapter_not_implemented"
            )

        current = self.config.get(
            "active_broker_profile"
        )
        if current and current != profile_id:
            store = getattr(
                self.company,
                "store",
                None,
            )
            pending = []
            if store is not None:
                pending = store.list_execution_intents(
                    limit=1000,
                    statuses=(
                        "submitting",
                        "uncertain",
                        "acknowledged",
                    ),
                    venue="binance",
                )
            else:
                reliability = getattr(
                    self.company,
                    "execution_reliability",
                    None,
                )
                if (
                    reliability is not None
                    and reliability.summary().get(
                        "recovery_required",
                        0,
                    )
                    > 0
                ):
                    pending = [{"status": "unresolved"}]
            if pending:
                raise SettingsError(
                    "broker_switch_blocked_by_unresolved_execution_intents"
                )
        self._save_config(
            {"active_broker_profile": str(profile_id)}
        )
        store = getattr(self.company, "store", None)
        if store is not None:
            self.company.execution_reliability = (
                DurableExecutionJournal(
                    store,
                    venue="binance",
                    environment=profile["environment"],
                )
            )
        return self.get_settings()["brokers"]
