import os
from pathlib import Path

if "CAOS_STATE_DB" not in os.environ:
    local = os.getenv("LOCALAPPDATA")
    if local:
        os.environ["CAOS_STATE_DB"] = str(
            Path(local) / "CAOS" / "caos.db"
        )

from caos.cli import main


if __name__ == "__main__":
    main()
