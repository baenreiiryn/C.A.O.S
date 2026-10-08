import os
import uuid
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from caos.app_settings import (
    MemoryCredentialVault,
    RuntimeSettingsService,
    SettingsError,
    WindowsCredentialVault,
)
from caos.llm import OllamaClient, OpenAICompatClient, StaticLLM


class FakeReliability:
    def __init__(self, recovery_required=0):
        self.recovery_required = recovery_required

    def summary(self):
        return {
            "recovery_required": self.recovery_required,
        }


def make_service(*, recovery_required=0):
    config = {
        "version": 1,
        "provider": "static",
        "model": "qwen3:8b",
        "base_url": "",
        "broker_profiles": [],
        "active_broker_profile": None,
    }
    persisted = []

    def persist(proposal):
        saved = dict(proposal)
        persisted.append(saved)
        return saved

    caos = SimpleNamespace(
        llm=StaticLLM('{"tool":"status","args":{}}')
    )
    company = SimpleNamespace(
        execution_reliability=FakeReliability(
            recovery_required
        )
    )
    vault = MemoryCredentialVault()
    service = RuntimeSettingsService(
        caos,
        company,
        config,
        persist,
        vault,
    )
    return service, caos, config, persisted, vault


class RuntimeLLMSettingsTests(unittest.TestCase):
    def test_save_ollama_changes_live_llm_without_company_reset(self):
        service, caos, config, persisted, _ = make_service()
        result = service.save_llm(
            provider="ollama",
            model="qwen3:14b",
            base_url="http://127.0.0.1:11434",
        )
        self.assertIsInstance(caos.llm, OllamaClient)
        self.assertEqual(caos.llm.model, "qwen3:14b")
        self.assertEqual(result["provider"], "ollama")
        self.assertEqual(config["provider"], "ollama")
        self.assertEqual(persisted[-1]["model"], "qwen3:14b")

    def test_openai_key_is_vaulted_not_persisted(self):
        service, caos, config, persisted, vault = make_service()
        result = service.save_llm(
            provider="openai-compatible",
            model="local-model",
            base_url="http://127.0.0.1:1234/v1",
            api_key="super-secret-key",
        )
        self.assertIsInstance(caos.llm, OpenAICompatClient)
        self.assertTrue(result["api_key_configured"])
        self.assertEqual(
            vault.get("llm:openai-compatible:api_key"),
            "super-secret-key",
        )
        self.assertNotIn(
            "super-secret-key",
            str(config),
        )
        self.assertNotIn(
            "super-secret-key",
            str(persisted),
        )

    @patch("caos.app_settings._json_get")
    def test_ollama_model_discovery(self, get_json):
        get_json.return_value = {
            "models": [
                {"name": "qwen3:8b"},
                {"name": "qwen3:14b"},
            ]
        }
        service, *_ = make_service()
        result = service.discover_models(
            provider="ollama",
            base_url="http://127.0.0.1:11434",
        )
        self.assertEqual(
            result["models"],
            ["qwen3:14b", "qwen3:8b"],
        )
        get_json.assert_called_once_with(
            "http://127.0.0.1:11434/api/tags"
        )

    @patch("caos.app_settings._json_get")
    def test_openai_model_discovery_uses_vault_key(
        self,
        get_json,
    ):
        get_json.return_value = {
            "data": [{"id": "model-a"}]
        }
        service, _, _, _, vault = make_service()
        vault.set(
            "llm:openai-compatible:api_key",
            "vault-key",
        )
        result = service.discover_models(
            provider="openai-compatible",
            base_url="http://localhost:1234/v1",
        )
        self.assertEqual(result["models"], ["model-a"])
        _, kwargs = get_json.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer vault-key",
        )


class BrokerSettingsTests(unittest.TestCase):
    def test_broker_secrets_are_never_returned_or_persisted(self):
        service, _, config, persisted, vault = make_service()
        profile = service.save_broker_profile(
            profile_id=None,
            label="My Bybit TESTNET",
            provider="bybit",
            environment="testnet",
            api_key="broker-key",
            api_secret="broker-secret",
        )
        profile_id = profile["id"]
        self.assertTrue(profile["api_key_configured"])
        self.assertTrue(profile["api_secret_configured"])
        self.assertEqual(
            vault.get(
                f"broker:{profile_id}:api_key"
            ),
            "broker-key",
        )
        self.assertEqual(
            vault.get(
                f"broker:{profile_id}:api_secret"
            ),
            "broker-secret",
        )
        serialized = str(
            {
                "config": config,
                "persisted": persisted,
                "settings": service.get_settings(),
            }
        )
        self.assertNotIn("broker-key", serialized)
        self.assertNotIn("broker-secret", serialized)

    def test_unsupported_adapter_profile_can_be_saved_but_not_activated(self):
        service, *_ = make_service()
        profile = service.save_broker_profile(
            profile_id=None,
            label="Future Binance",
            provider="binance",
            environment="testnet",
            api_key="key",
            api_secret="secret",
        )
        with self.assertRaises(SettingsError):
            service.set_active_broker(profile["id"])

    def test_switch_is_blocked_by_unresolved_external_intents(self):
        service, *_ = make_service(recovery_required=1)
        first = service.save_broker_profile(
            profile_id=None,
            label="Bybit A",
            provider="bybit",
            environment="testnet",
            api_key="a",
            api_secret="a-secret",
        )
        second = service.save_broker_profile(
            profile_id=None,
            label="Bybit B",
            provider="bybit",
            environment="testnet",
            api_key="b",
            api_secret="b-secret",
        )
        service.set_active_broker(first["id"])
        with self.assertRaises(SettingsError):
            service.set_active_broker(second["id"])

    def test_active_profile_cannot_be_deleted(self):
        service, *_ = make_service()
        profile = service.save_broker_profile(
            profile_id=None,
            label="Bybit",
            provider="bybit",
            environment="testnet",
            api_key="key",
            api_secret="secret",
        )
        service.set_active_broker(profile["id"])
        with self.assertRaises(SettingsError):
            service.delete_broker_profile(
                profile["id"]
            )


if __name__ == "__main__":
    unittest.main()



@unittest.skipUnless(
    os.name == "nt",
    "Windows Credential Manager test",
)
class WindowsCredentialVaultTests(unittest.TestCase):
    def test_native_windows_credential_roundtrip(self):
        vault = WindowsCredentialVault(
            namespace="CAOS-TEST"
        )
        key = "roundtrip-" + uuid.uuid4().hex
        try:
            vault.set(key, "secret-value-123")
            self.assertEqual(
                vault.get(key),
                "secret-value-123",
            )
            vault.delete(key)
            self.assertIsNone(vault.get(key))
        finally:
            try:
                vault.delete(key)
            except Exception:
                pass
