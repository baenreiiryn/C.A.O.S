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
from .testnet import BybitTestnetClient


SETTINGS_API_VERSION = "settings/v1"
SUPPORTED_BROKERS = {
    "bybit": {
        "label": "Bybit",
        "environments": ("testnet",),
        "activatable": True,
    },
    "binance": {
        "label": "Binance",
        "environments": ("testnet",),
        "activatable": False,
    },
    "okx": {
        "label": "OKX",
        "environments": ("demo",),
        "activatable": False,
    },
    "kraken": {
        "label": "Kraken",
        "environments": ("demo",),
        "activatable": False,
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
            if isinstance(row, dict)
        ]

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
        return {
            "version": SETTINGS_API_VERSION,
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
            "brokers": {
                "supported": SUPPORTED_BROKERS,
                "profiles": profiles,
                "active_profile_id": self.config.get(
                    "active_broker_profile"
                ),
            },
        }

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
                or "http://127.0.0.1:11434"
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
        if (
            provider != "static"
            and requested
            and discovered["models"]
            and requested not in discovered["models"]
        ):
            return {
                **discovered,
                "ok": False,
                "message": (
                    f"Model {requested!r} was not returned "
                    "by the provider."
                ),
            }
        return {
            **discovered,
            "ok": True,
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
            llm = OllamaClient(
                model,
                base_url
                or "http://127.0.0.1:11434",
            )
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
        if provider != "bybit" or environment != "testnet":
            raise SettingsError(
                "broker_adapter_not_implemented"
            )
        client = BybitTestnetClient(
            api_key=key,
            api_secret=secret,
        )
        info = client.get_api_key_info()
        return {
            "ok": True,
            "profile_id": profile_id,
            "provider": provider,
            "environment": environment,
            "read_only": info.get("read_only"),
            "permissions": info.get("permissions", {}),
            "message": "Broker credentials authenticated.",
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
                raise SettingsError(
                    "broker_switch_blocked_by_unresolved_execution_intents"
                )
        self._save_config(
            {"active_broker_profile": str(profile_id)}
        )
        return self.get_settings()["brokers"]
