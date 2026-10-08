# Windows Installer

C.A.O.S v0.7.0 ships a self-contained Windows installer for the standalone Trade Company.

## What gets installed

```text
%LOCALAPPDATA%\Programs\CAOS\
├─ CAOS-Trade-Company.exe
└─ caos.exe
```

The application runtime is bundled into the executables. A separate Python installation is not required.

The installer creates a Start Menu folder named **C.A.O.S** with:

- **C.A.O.S Trade Company** — starts the graphical launcher;
- **C.A.O.S CLI** — opens a command prompt in the installation directory.

Optional installer tasks:

- desktop shortcut;
- start the Trade Company when the current Windows user signs in.

## Runtime state

Program files and user state are intentionally separated.

Persistent Company state:

```text
%LOCALAPPDATA%\CAOS\caos.db
```

Launcher configuration:

```text
%LOCALAPPDATA%\CAOS\launcher.json
```

The packaged CLI defaults to the same `caos.db`, so the GUI and CLI operate on the same Trade Company.

Uninstalling the program does not remove the state directory automatically.

## First launch

The first launch opens the **Founding Charter**.

The wizard configures:

- Company capital;
- initial Trader bucket;
- Trader stop floor;
- default maximum Trader exposure;
- operational Trader concurrency cap;
- maximum Company drawdown;
- market/strategy targets;
- daemon cycle interval;
- Arcane Trading City port;
- local AI provider;
- local model name;
- optional OpenAI-compatible/Ollama base URL.

Example targets:

```text
BTCUSDT:long:momentum
BTCUSDT:long:momentum,ETHUSDT:long:trend
```

After the charter is accepted:

1. the SQLite state database is created;
2. the Trade Company is initialized;
3. the autonomous PAPER daemon starts in a background thread;
4. the themed city HTTP server starts on localhost;
5. the Arcane Trading City opens in the default browser;
6. a small Windows control window remains available to reopen or stop the Company.

The default city address is:

```text
http://127.0.0.1:5191
```

## AI provider

The default provider in the Windows wizard is `static`, so the application can start without Ollama or another model server.

Available provider settings:

```text
static
ollama
openai-compatible
```

The autonomous deterministic market loop does not require a local LLM on every tick.

## Bybit TESTNET

The installer and first-run wizard do not store broker credentials.

When using the TESTNET administration tools, credentials remain environment variables:

```powershell
$env:BYBIT_TESTNET_API_KEY="..."
$env:BYBIT_TESTNET_API_SECRET="..."
```

Money-moving TESTNET submission keeps the existing explicit human gate.

LIVE execution remains unavailable.

## Building locally

Requirements for producing the installer:

- Windows x64;
- Python 3.11;
- PyInstaller;
- Inno Setup 6.

Equivalent build steps:

```powershell
python -m pip install .
python -m pip install pyinstaller

pyinstaller --noconfirm --clean --onefile --windowed --name CAOS-Trade-Company --collect-submodules caos --hidden-import tkinter --hidden-import tkinter.ttk --hidden-import tkinter.messagebox installer/company_app.py

pyinstaller --noconfirm --clean --onefile --console --name caos --collect-submodules caos installer/cli_app.py

& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" installer\caos.iss
```

Output:

```text
installer-output\CAOS-Setup.exe
```

## GitHub Actions

The workflow:

```text
.github/workflows/windows-installer.yml
```

runs on `windows-latest` and:

1. installs C.A.O.S;
2. runs the complete unit-test suite;
3. builds the windowed Trade Company executable;
4. builds the console CLI executable;
5. smoke-tests both packaged executables;
6. installs Inno Setup;
7. creates `CAOS-Setup.exe`;
8. uploads it as the `CAOS-Windows-Installer` workflow artifact.

## Signing

The current installer is unsigned.

Windows SmartScreen may therefore show an unrecognized-publisher warning. Code signing can be added later to the build workflow without changing the application architecture.
