import os
from pathlib import Path

if "CAOS_STATE_DB" not in os.environ:
    local = os.getenv("LOCALAPPDATA")
    if local:
        os.environ["CAOS_STATE_DB"] = str(
            Path(local) / "CAOS" / "caos.db"
        )

if os.name == "nt":
    try:
        from caos.app_settings import WindowsCredentialVault
        from caos.windows_app import load_launcher_config

        launcher = load_launcher_config()
        if launcher:
            active_id = launcher.get(
                "active_broker_profile"
            )
            profiles = launcher.get(
                "broker_profiles",
                [],
            )
            active = next(
                (
                    row
                    for row in profiles
                    if row.get("id") == active_id
                ),
                None,
            )
            if (
                active
                and active.get("provider") == "bybit"
                and active.get("environment") == "testnet"
            ):
                vault = WindowsCredentialVault()
                key = vault.get(
                    f"broker:{active_id}:api_key"
                )
                secret = vault.get(
                    f"broker:{active_id}:api_secret"
                )
                if key and "BYBIT_TESTNET_API_KEY" not in os.environ:
                    os.environ["BYBIT_TESTNET_API_KEY"] = key
                if (
                    secret
                    and "BYBIT_TESTNET_API_SECRET"
                    not in os.environ
                ):
                    os.environ[
                        "BYBIT_TESTNET_API_SECRET"
                    ] = secret
    except Exception:
        # The CLI remains usable for PAPER/admin commands even if
        # the Windows credential vault is unavailable.
        pass

from caos.cli import main


if __name__ == "__main__":
    main()
