# Windows Installer

C.A.O.S v0.8.12 ships a self-contained Windows installer for the standalone Trade Company with managed Ollama, managed Forecast/Sentiment Oracles, a hardened GitHub self-updater, autonomous market/timeframe/strategy selection, live 1-minute Trader charts, editable post-onboarding Company policy, a read-only lateral LLM chat, explicit Start / graceful Stop / Emergency Stop / Reset Emergency controls, and a local execution gate for PAPER, Binance Spot TESTNET, and human-confirmed Binance production orders. v0.8.12 switches updater manifest/package resolution to the GitHub release asset API first, with browser URL fallback, to avoid release-asset HTTP 404 failures.

## What gets installed

```text
%LOCALAPPDATA%\Programs\CAOS\
├─ CAOS-Trade-Company.exe
├─ caos.exe
├─ experts-runtime\
│  ├─ caos-experts.exe
│  └─ LICENSE-Kronos.txt
└─ ollama\
   ├─ ollama.exe
   └─ ...portable GPU/runtime libraries
```

The application runtime is bundled into the executables and the official portable Ollama runtime is installed beside them. A separate Python or Ollama installation is not required. The portable Ollama package is large, so v0.8.0's installer is substantially larger than v0.7.x.

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
- market selection mode (**AUTO** by default);
- manual market/strategy targets used only as fallback/debug when MANUAL is selected;
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


In **AUTO** mode those examples do not constrain the Traders. The autonomous Scout discovers liquid Binance Spot USDT markets, evaluates the supported timeframes against every registered strategy that is allowed for production, and assigns the highest-ranked available combination. The configured target list is consulted only in MANUAL mode.

After the charter is accepted:

1. the SQLite state database is created;
2. the Trade Company is initialized in **STOPPED** state;
3. the background daemon starts only for market/news observation and risk-reducing drain logic; it cannot open new risk until the operator presses **Start**;
4. the themed city HTTP server starts on localhost;
5. the Arcane Trading City opens in the default browser with **Start**, **Stop**, and **Emergency** controls;
6. **Stop** blocks new entries and leaves existing confirmed positions in a **STOPPING** drain state until they close through their normal risk-reducing path;
7. **Emergency** cancels pending PAPER entries immediately; in REAL · MANUAL it creates close proposals that still require your per-order confirmation before any production order is sent;
8. the execution-mode selector is available only in the local city UI and always resets to PAPER on restart;
9. a small Windows control window remains available to reopen or stop the Company process.

The default city address is:

```text
http://127.0.0.1:5191
```


## GitHub self-update

From **v0.8.8** onward, normal application upgrades no longer require uninstalling or running the full setup manually.

Open:

```text
Arcane Trading City
  → ⚙ Settings
  → Update Center · GitHub Releases
```

The updater checks the repository's latest stable GitHub Release. Each release publishes:

```text
CAOS-Setup.exe               full installer
CAOS-Update.zip              lightweight in-place application update
CAOS-Update.json             version + SHA-256 manifest
CAOS-Experts-Runtime.zip     optional managed oracle sidecar
CAOS-Experts-Runtime.json    oracle-runtime SHA-256 manifest
```

The program downloads and verifies `CAOS-Update.zip`. Installation is allowed only when the Company is fully **STOPPED**, all PAPER positions/orders are flat, and no external/REAL execution remains unresolved. The update is then scheduled for process exit. A detached PowerShell helper waits for the running application to terminate, backs up both installed executables, replaces them, and relaunches the Trade Company. If replacement fails, the previous executables are restored.

Persistent data and secrets remain outside the update payload. Normal updates preserve `caos.db`, `launcher.json`, the managed Ollama model store, Windows Credential Manager entries, and the installed portable Ollama runtime.

The first version that contains the updater is **v0.8.8**, so older installations need one final manual installation of v0.8.8. After that, later releases can be installed from inside the application.

## Managed Forecast / Sentiment Oracles

From **v0.8.9**, Settings contains **Arcane Nexus · Oracles**.

The main application remains dependency-light. Torch, Transformers, Chronos and the pinned Kronos model source are packaged into a separate local sidecar:

```text
caos-experts.exe
http://127.0.0.1:11436
```

The runtime is CPU-first so Ollama/your local LLM can keep the RTX GPU VRAM. Model weights are not embedded in C.A.O.S; Hugging Face downloads are cached under:

```text
%LOCALAPPDATA%\CAOS\expert-models\
```

Default configuration:

```text
Kronos-small      enabled / recommended
ModernFinBERT     enabled / recommended
Chronos-2         disabled / optional baseline
```

Controls:

- **Install Expert Runtime** — for lightweight-updated installations that do not yet have the sidecar;
- **Save Oracles** — persists enabled specialists;
- **Start Runtime / Stop Runtime** — controls the local sidecar process;
- **Download / Load Enabled** — explicitly loads enabled model weights;
- **Unload Models** — frees the sidecar's loaded model memory without changing configuration.

The Oracles are advisory. ModernFinBERT feeds the news-sentiment path when loaded. Loaded forecast models may only penalize a top AUTO candidate when their ensemble contradicts a long setup. They cannot create an order, raise position sizing, change PAPER/REAL mode, or bypass risk/compliance gates.

### Execution Gate

Click the execution-mode rune in the Arcane Trading City to open the local Execution Gate.

- **PAPER** — autonomous simulation using the internal PAPER broker.
- **BINANCE TESTNET** — autonomous Spot Testnet submission after you manually select TESTNET mode.
- **REAL · MANUAL** — agents may create Binance production proposals, but every order stays in `prepared` state until you click **Confirm Order** for that exact `intent_id`.
- Selecting REAL requires typing `ENABLE REAL`, the Company must be STOPPED, and the internal execution ledger must be flat.
- A production confirmation is scoped to one exact intent via `CONFIRM <intent_id>`; it cannot authorize a different order.
- Restarting Trade Company always returns execution mode to PAPER.
- The LLM/Company Cell has no command for changing execution mode or confirming a production order.

## Default news intelligence

Fresh v0.8.0 installations start with the Whispering Tankard news catalog already configured in `launcher.json`.

Enabled defaults include crypto/market/editorial sources plus official SEC, Federal Reserve and Bank of Japan feeds. The Arcane Trading City **Settings → Whispering Tankard** page lets the user:

- enable/disable or remove sources;
- restore the shipped defaults;
- test RSS/Atom URLs;
- paste a normal HTTPS news-site URL and discover its feed;
- add custom sources;
- preview the latest headlines.

News source settings contain no secrets.

Upgrading an existing v0.7.2 or v0.7.3 installation preserves the existing database and launcher config. If `news_sources` is absent, v0.8.0 adds the built-in catalog automatically.

News is context/risk evidence only. It cannot create orders, and a custom feed cannot independently trigger the critical hard block on new risk.

## AI provider

The default provider in the Windows wizard is `static`, so the application can start without Ollama or another model server.

Available provider settings:

```text
static
ollama
openai-compatible
```

The autonomous deterministic market loop does not require a local LLM on every tick.

## Persistent settings after first launch

The Founding Charter is only the first-run setup. Once the Company exists, configuration remains available from the **⚙ Settings** button in the Arcane Trading City.

### Arcane Nexus — LLM

You can change:

- provider (`static`, `ollama`, `openai-compatible`);
- model;
- base URL;
- optional OpenAI-compatible API key.

The UI can discover models from Ollama and OpenAI-compatible `/models` endpoints, test connectivity, and switch the live `caos.llm` object without resetting Treasury, Traders, PAPER positions, Research Factory state or rollout state.

#### Managed Ollama

The Windows installer carries the official portable Ollama runtime under:

```text
%LOCALAPPDATA%\Programs\CAOS\ollama\
```

Trade Company starts it only on demand and binds it to:

```text
http://127.0.0.1:11435
```

This avoids colliding with a separately installed Ollama, whose normal endpoint is `11434`.

Managed model storage:

```text
%LOCALAPPDATA%\CAOS\ollama-models\
```

From **Settings → Arcane Nexus · Managed Ollama** the user can:

1. click **Choose GGUF** to open a native Windows file picker;
2. select a local `.gguf` model file;
3. optionally change the imported model name;
4. click **Apply Local Model**;
5. let Trade Company run `ollama create` against the selected GGUF;
6. automatically switch the active provider/model to the managed endpoint;
7. use **Start Ollama** and **Stop Ollama** without a terminal.

Importing a GGUF registers it inside Ollama's managed model store. The original source file is not treated as an API endpoint.

LLM API keys are stored in Windows Credential Manager.

### Broker Embassy

Broker profiles can be added or edited after onboarding. Broker metadata is stored in `launcher.json`, while API keys/secrets are stored in Windows Credential Manager.

Binance Japan / Spot is the supported broker. `spot-testnet` is the human-gated test-order environment; `production-readonly` authenticates a real Binance Japan account while keeping production order submission disabled.

The active broker cannot be switched while unresolved external execution intents exist.

The packaged `caos.exe` loads the active Binance Spot Testnet profile from Windows Credential Manager automatically, so installed users do not need to configure credentials through PowerShell environment variables.

## Binance Japan / Spot

The installer and first-run wizard do not store broker credentials directly. Configure a broker later in **Settings → Broker Embassy**; secrets are stored in Windows Credential Manager.

Supported environments:

```text
spot-testnet          human-gated Binance Spot Testnet orders
production-readonly  real Binance Japan account metadata, no production orders
```

For CLI/development use without a saved Broker Embassy profile:

```powershell
$env:BINANCE_TESTNET_API_KEY="..."
$env:BINANCE_TESTNET_API_SECRET="..."
```

Money-moving Spot Testnet submission keeps the explicit `ARM TESTNET` human gate. Production order submission and LIVE remain unavailable.

## Building locally

Requirements for producing the installer:

- Windows x64;
- Python 3.11;
- PyInstaller;
- Inno Setup 6.

Equivalent build steps require the portable Ollama runtime to be extracted to `ollama-runtime\` first. The GitHub Actions workflow downloads pinned Ollama v0.40.1 and verifies its SHA-256 before packaging.

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
3. downloads the pinned official Ollama portable runtime and verifies its SHA-256;
4. builds the windowed Trade Company executable;
5. builds the console CLI executable;
6. smoke-tests both packaged executables;
7. installs Inno Setup;
8. creates `CAOS-Setup.exe` with the managed Ollama runtime;
9. uploads it as the `CAOS-Windows-Installer` workflow artifact.

## Signing

The current installer is unsigned.

Windows SmartScreen may therefore show an unrecognized-publisher warning. Code signing can be added later to the build workflow without changing the application architecture.
