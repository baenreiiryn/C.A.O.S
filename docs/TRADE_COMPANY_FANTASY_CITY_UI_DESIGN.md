# Trade Company Fantasy City UI — Design Goal

Status: **COMPLETE**

This document defines the visual language and first-screen information architecture for the Trade Company standalone interface.

The goal is intentionally presentation-only. No trading, Treasury, risk, execution, persistence, or C.A.O.S rule may depend on the fantasy theme.

---

## 1. Core concept

The long-term Drizzt interface is a high-magic medieval kingdom.

- **Drizzt** is the King and global Company Supervisor.
- **Each autonomous company/cell** is represented as a city in the kingdom.
- **Each subsystem, agent, or operational role** inside a company is represented as a building, guild, character, or magical institution inside that city.
- Clicking a location or character opens the real operational details behind that visual metaphor.
- Asking Drizzt to show a company should eventually navigate directly to that city's view.

For the current standalone Trade Company, Drizzt is not required and the interface opens directly into the Trade Company city.

The future relationship is:

```text
                       DRIZZT
                         KING
                          |
                 Kingdom / Company Map
                          |
          +---------------+---------------+
          |               |               |
          v               v               v
     Trade City      Content City      Future City
          |
          v
 Trade Company + C.A.O.S
```

The current standalone relationship is simply:

```text
Trade Company City
        |
        v
Trade Company + C.A.O.S
```

---

## 2. Design principle: visualization, not simulation logic

The fantasy interface is a view over real system state.

```text
Trade Company / C.A.O.S
          |
          v
CompanyControlPort
          |
          v
Presentation / City ViewModel
          |
          v
Fantasy City UI
```

The UI must never become the source of truth for:

- capital;
- Trader lifecycle;
- market reservations;
- order sizing;
- exposure limits;
- kill switches;
- reconciliation;
- strategy state;
- Company policy;
- broker state.

Fantasy terms are aliases only.

For example:

```text
Royal Treasury
      =
Treasury

Mage of Risk
      =
CompanyRiskGovernor

Adventurer A
      =
Trader A
```

If the themed UI is removed, the Trade Company must continue to operate exactly the same way.

---

## 3. Visual identity

### Style

The city should look like **high fantasy**, not realistic medieval poverty and not a generic RPG inventory screen.

Visual characteristics:

- prosperous magical trading city;
- stone towers, bridges, plazas, guild halls and arcane architecture;
- floating crystals, glowing runes and magical instruments;
- warm tavern light contrasting with cool arcane towers;
- distant mountains / magical sky / city walls;
- readable silhouettes for every important building;
- animated but calm ambient life;
- visual state changes driven by Company health.

The interface should feel like watching a living city work rather than looking at a spreadsheet.

### Perspective

Preferred first implementation:

**2.5D / isometric illustrated city view** with interactive hotspots.

Reasons:

- all important locations can remain visible at once;
- easier to implement than a fully navigable 3D world;
- supports animated characters and buildings;
- works in desktop browser;
- locations can be clicked directly;
- can later be upgraded without changing the backend.

### Technical fallback

The existing technical dashboard remains available as an optional diagnostic view.

The fantasy city becomes the primary human-facing operator interface.

---

## 4. System-to-world mapping

### 4.1 Trade Company

**Real component:** TradeCompany

**Fantasy equivalent:** The City itself

The city represents the complete autonomous company.

City-wide visual state reflects:

- Company health;
- marked Company equity;
- operational activity;
- active alerts;
- emergency stop;
- number of active Traders.

Healthy Company:

- populated streets;
- active lanterns;
- open gates;
- normal magical glow;
- banners moving normally.

Attention state:

- warning bell or amber beacon;
- one or more buildings visibly requesting attention;
- less dramatic than emergency state.

Critical state:

- red magical wards;
- city alarm bell;
- affected district highlighted.

Emergency stop:

- city gates close;
- protective barrier activates;
- trading guild becomes inactive;
- risk tower emits a clear red ward.

---

### 4.2 Company Supervisor

**Real component:** CompanySupervisor

**Fantasy equivalent:** The Governor / Royal Steward in the Citadel

Current standalone mode:

- represented by a **Royal Steward** because Drizzt is not yet connected.

Future Drizzt mode:

- the Steward reports upward to King Drizzt;
- Drizzt may appear in the kingdom-level interface rather than physically living in every city.

Location:

**Citadel of Oversight**

What the Steward visually monitors:

- city health;
- alerts;
- reconciliation;
- Trader states;
- C.A.O.S health;
- operational cap;
- exposure;
- risk state.

Clicking the Steward/Citadel opens:

- current audit status;
- alert list;
- metrics;
- recent critical events;
- emergency controls permitted by CompanyControlPort.

---

### 4.3 Treasury

**Real component:** Treasury

**Fantasy equivalent:** Royal Treasury / Grand Vault

Primary character:

**Royal Treasurer**

Supporting visuals:

- coin vaults;
- magical balance scale;
- ledger book;
- locked chests;
- glowing reserve crystal.

Represents:

- Treasury Reserve;
- Company realized equity;
- capital allocated to Traders;
- ledger entries;
- spawn funding capacity.

Visual state examples:

High reserve:

- fuller vault;
- bright reserve crystal.

Low reserve:

- fewer filled coffers;
- no alarm unless this creates an actual Company issue.

Enough capital to fund a new Trader:

- a sealed funding chest appears ready beside the Treasurer.

Ledger activity:

- Treasurer writes in the great ledger;
- short animation whenever capital is allocated/returned.

Click opens:

- reserve;
- balances by Trader;
- realized Company equity;
- initial Trader bucket;
- financial spawn capacity;
- full capital ledger.

---

### 4.4 Capital Allocator

**Real component:** CapitalAllocator

**Fantasy equivalent:** Master of Coin / Treasury Quartermaster

Location:

inside or immediately adjacent to the Royal Treasury.

Role:

- grants operating purses to new Traders;
- receives returned capital;
- determines whether the Treasury can fund a new Trader;
- applies the operational capacity rule before funding.

Visual metaphor:

The Master of Coin prepares a sealed purse/chest for an adventurer.

Treasury-funded spawn:

```text
Treasury chest
     ->
new Adventurer
```

Growth-funded spawn:

```text
surplus returned from Adventurer A
     ->
Royal Treasury
     ->
new Adventurer B
```

The UI must never visually imply that A owns B.

---

### 4.5 Trader Registry

**Real component:** TraderRegistry

**Fantasy equivalent:** Adventurers' Guild roster

Location:

**Grand Trading Guild**

Each Trader is a persistent named guild member:

- Trader A;
- Trader B;
- Trader C;
- etc.

The fantasy character class is cosmetic and may differ per Trader:

- knight;
- ranger;
- spellblade;
- archer;
- battle mage;
- rogue;
- artificer.

Class must never imply trading behavior unless explicitly configured later.

The Guild roster represents:

- active Traders;
- waiting Traders;
- paused Traders;
- halted Traders;
- retired Traders.

---

### 4.6 Trader

**Real component:** Trader

**Fantasy equivalent:** Individual Adventurer / Merchant Champion

Each Trader has a clickable character.

Displayed visually around the character:

- Trader ID;
- current market;
- strategy;
- equity;
- status;
- requested exposure;
- maximum exposure;
- current position/exposure.

State mapping:

```text
WAITING_ASSIGNMENT
  -> inside Guild Hall studying the quest board

ACTIVE
  -> on expedition / at mission table / leaving city gate

PAUSED
  -> seated inside Guild Hall, equipment put aside

EVALUATING
  -> speaking with strategists / examining maps

HALTED
  -> in infirmary / under protective ward

RETIRED
  -> Hall of Veterans / inactive roster
```

No state should ridicule or punish the Trader character; states are operational, not moral judgments.

Clicking a Trader opens the Trader detail panel.

Trader detail includes:

- ID;
- status;
- mode;
- assigned symbol and direction;
- strategy;
- current equity;
- realized and marked values;
- requested trade exposure %;
- maximum trade exposure %;
- requested trade notional;
- maximum trade notional;
- open exposure;
- fills/trades;
- performance data when available;
- pause/resume controls if permitted.

---

### 4.7 Company Risk Governor

**Real component:** CompanyRiskGovernor

**Fantasy equivalent:** Archmage of Wards / Mage of Risk

Location:

**Tower of Wards**

Visual:

- mage studying large floating parchments;
- magical circles representing exposure boundaries;
- protective city wards;
- crystal showing Company drawdown;
- runic seals corresponding to risk gates.

Represents:

- per-Trader exposure ceiling;
- marked Trader equity;
- Company drawdown;
- Company kill switch;
- market assignment validation;
- risk-reducing exception path.

Normal:

- calm blue/gold runes.

Attention:

- amber sigils.

Critical:

- red runes and active protective barrier.

Kill switch:

- city-wide ward visibly closes.

Click opens:

- current Company drawdown;
- kill-switch state;
- max notional per Trader;
- current marked equity;
- exposure summaries;
- risk-related alerts.

---

### 4.8 Strategy Diversity

**Real component:** StrategyDiversity

**Fantasy equivalent:** Council of Banners

Location:

a chamber connected to the Tower of Wards or Guild.

Visual metaphor:

Each active Trader/strategy has a banner.

If too many banners represent the same direction or strategy family, the chamber visually groups them and marks concentration.

Represents:

- long/short directional concentration;
- strategy-family concentration;
- diversity warnings.

Click opens:

- active production count;
- long share;
- short share;
- strategy-family shares;
- diversity warnings.

---

### 4.9 Market Scout

**Real component:** MarketScout

**Fantasy equivalent:** Ranger / Royal Pathfinder

Location:

**Scout Lodge at the City Gate**

Visual:

- ranger returning from expeditions;
- maps;
- compass;
- magical falcon;
- pinned routes.

Represents:

- market scanning;
- discovered opportunities;
- regime-derived opportunity scores.

During a scan:

- Ranger examines the world map.

New opportunity:

- messenger bird/map marker appears.

Click opens:

- scanned markets;
- discovered opportunities;
- score;
- regime;
- expiry;
- direction;
- candidate strategies.

---

### 4.10 Opportunity Registry

**Real component:** OpportunityRegistry

**Fantasy equivalent:** Quest Board

Location:

outside the Trading Guild / central market square.

Each market opportunity is a quest parchment.

Quest states:

```text
DISCOVERED
  -> parchment being prepared

VALIDATED
  -> parchment receives guild seal

AVAILABLE
  -> pinned to Quest Board

RESERVED
  -> ribbon / crest of assigned Trader

ACTIVE
  -> Trader portrait appears beside quest

EXPIRED
  -> parchment fades / is moved to archive
```

Displayed information:

- symbol;
- direction;
- score;
- regime;
- expiry;
- owner;
- candidate strategies.

---

### 4.11 Market Allocator

**Real component:** MarketAllocator

**Fantasy equivalent:** Guild Questmaster

Location:

inside the Trading Guild beside the Quest Board.

Role:

- assigns quests to Adventurers;
- prevents production Traders from sharing an occupied market;
- allows configured overlap in Training.

Visual:

Questmaster physically moves a sealed quest parchment from the board to a Trader.

Click opens:

- current market assignments;
- occupied markets;
- waiting Traders;
- available opportunities.

---

### 4.12 Market Regime / quantitative market analysis

**Real components:** C.A.O.S quant/regime functions

**Fantasy equivalent:** Arcane Observatory

Primary character:

**Astromancer / Market Seer**

Visual:

- magical telescope;
- rotating astrolabe;
- constellations;
- floating market charts represented as celestial glyphs.

Represents:

- trend;
- volatility;
- current regime;
- deterministic market analysis.

Visual regime examples:

- trend up -> rising constellation;
- trend down -> descending constellation;
- range -> orbiting balanced glyph;
- high volatility -> unstable magical storm.

Click opens real numerical regime/quant data.

---

### 4.13 News / sentiment

**Real components:** NewsAnalyzer, RSSNewsClient, FinBERT/sentiment evidence when configured

**Fantasy equivalent:** The Bard of Rumors

Location:

**The Whispering Tankard Tavern**

Visual:

- bard playing music;
- patrons talking;
- travelers arriving;
- notice scraps;
- messengers bringing rumors.

Represents:

- external news;
- sentiment;
- market context;
- recent stories.

The Bard does not make final trading decisions.

Click opens:

- recent news items;
- sources;
- sentiment;
- summarized context;
- timestamps.

If no news feeds are configured:

- Bard remains present but the tavern says no messengers have arrived.

---

### 4.14 Strategy Registry

**Real component:** CompanyStrategyRegistry

**Fantasy equivalent:** Hall of Combat Manuals / Strategy Library

Location:

inside the Trading Guild or Academy.

Primary character:

**Guild Tactician**

Represents:

- registered strategies;
- strategy families;
- parameters;
- which strategies are available for assignment.

Click opens:

- strategy ID;
- family;
- fast/slow values;
- stop/target;
- threshold;
- usage by Traders.

---

### 4.15 Training Arena

**Real component:** TrainingArena

**Fantasy equivalent:** Grand Tournament Arena

Visual:

- champion banners;
- challenger banners;
- training combat;
- magical scoreboard.

Represents fair experiments where:

- same market;
- same period;
- same capital;
- same cost assumptions;
- different strategy variants.

Current experiment view:

```text
Champion / Challenger Tournament

A — Strategy 1
B — Strategy 2
C — Strategy 3
...
```

Click opens:

- experiment ID;
- symbol;
- starting capital;
- cost;
- result ranking;
- profit factor;
- drawdown;
- PnL;
- robustness.

This location is the natural future home of Champion/Challenger workflows.

---

### 4.16 Improvement Manager

**Real component:** ImprovementManager

**Fantasy equivalent:** Royal Arcanist / Master Alchemist

Location:

**Arcane Workshop / Great Library**

Visual:

- alchemical instruments;
- grimoires;
- experimental crystals;
- research notes.

Represents:

- improvement proposals;
- investigation of degraded Traders;
- requests for new experiments;
- future Research Factory integration.

Current behavior:

The Arcanist proposes changes but cannot bypass Company policy or directly enable unsafe execution.

Click opens:

- proposal type;
- target;
- reason;
- evidence/metadata;
- whether human action is required.

---

### 4.17 Company Paper Book

**Real component:** CompanyPaperBook

**Fantasy equivalent:** Hall of Illusory Expeditions

Location:

beneath or beside the Trading Guild.

Visual concept:

A magical simulation chamber where Adventurers rehearse missions in illusion.

Represents:

- per-Trader paper accounts;
- simulated positions;
- fills;
- marked equity;
- reconciliation;
- paper exposure.

This communicates that PAPER activity is real Company logic but not real-money broker execution.

When mode is PAPER:

- city trading activity carries a subtle blue/ethereal visual indicator.

Future TESTNET/LIVE modes should use distinct unmistakable presentation states.

---

### 4.18 Paper/Execution/Risk path

**Real components:** Trader -> CompanyRiskGovernor -> C.A.O.S Risk -> broker/execution layer

**Fantasy equivalent:** Expedition Gate

Visual:

Before an Adventurer leaves the city:

1. Guild Questmaster gives the quest.
2. Mage of Risk applies the protective seal.
3. C.A.O.S Arcane Engine validates the route.
4. City Gate permits or denies the expedition.

The visual must never imply that clicking the gate manually bypasses those checks.

---

### 4.19 C.A.O.S

**Real component:** shared C.A.O.S engine

**Fantasy equivalent:** The Arcane Nexus

Location:

a central magical structure below/behind the Citadel, connected by glowing conduits to the rest of the city.

Possible visual form:

- giant arcane crystal;
- magical engine;
- ley-line nexus;
- ancient observatory core.

Represents shared services:

- quant;
- regime;
- forecasts;
- specialist models;
- execution-cost estimates;
- C.A.O.S Risk;
- supervisory health.

C.A.O.S is not a character and is not one Trader's personal intelligence.

Every district may visually connect to the Arcane Nexus through magical ley lines.

Click opens:

- engine health;
- loaded symbols;
- specialists;
- kill-switch state;
- technical diagnostics link.

---

### 4.20 Specialist models

**Real components:** Kronos, Chronos-2, ModernFinBERT and future qualified experts

**Fantasy equivalent:** Oracles / Sages attached to the Arcane Nexus

Examples:

- Kronos -> Oracle of Cycles;
- Chronos -> Keeper of Time;
- FinBERT -> Interpreter of Rumors.

These names are cosmetic aliases only.

Their visual presence depends on actual configured/qualified specialists.

Clicking an Oracle opens:

- actual model ID;
- qualification state;
- latest forecast/evidence;
- benchmark status.

Unqualified specialists must never be visually presented as trusted advisors.

---

### 4.21 Company Daemon

**Real component:** CompanyDaemon

**Fantasy equivalent:** The City's Heartbeat / Bell of Operations

Not necessarily a character.

Visual:

- central clock tower;
- magical pulse through ley lines;
- bell marking each operating cycle.

Represents the continuous loop:

```text
refresh
 -> scout
 -> opportunities
 -> assign
 -> paper cycle
 -> stop floor
 -> expansion
 -> audit
 -> checkpoint
```

If daemon is stopped:

- clock tower stops;
- a clear "City operations paused" indicator appears.

---

### 4.22 Checkpoint / recovery

**Real component:** CompanyCheckpoint + Store

**Fantasy equivalent:** Chronicle Vault / Memory Crystal

Location:

archive beneath the Citadel.

Visual:

- enchanted records;
- memory crystals;
- royal chronicle.

Represents:

- persisted state;
- last checkpoint;
- restore health;
- event history.

Normally this is background infrastructure and does not need to dominate the first screen.

---

### 4.23 CompanyControlPort

**Real component:** CompanyControlPort

**Fantasy equivalent:** Royal Command Seal

This is not shown as a physical agent in the city.

It is the formal interface through which:

- current standalone UI;
- future Drizzt;
- future external operator interfaces

interact with the Company.

All interactive fantasy UI actions must ultimately resolve to a permitted CompanyControlPort operation.

---

### 4.24 Operational Trader cap

**Real component:** operational_trader_cap / effective_trader_limit

**Fantasy equivalent:** Guild Capacity

Visual:

- number of active guild beds/crests/slots;
- e.g. "4 of 6 Adventurer Seals occupied."

This is explicitly a resource limit, not a financial risk limit.

---

### 4.25 Broker / future external execution

**Real component:** broker/exchange adapter

**Fantasy equivalent:** Merchant Gate / Caravan Portal

It sits outside the city walls conceptually.

The city prepares and approves expeditions; the external world executes them.

Broker credentials must never appear as fantasy items that can be casually manipulated from the city map.

---

## 5. First screen: Trade Company City

The first screen must answer four questions without opening any technical panel:

1. Is the Company healthy?
2. What are the Traders doing?
3. Is capital available / constrained?
4. Is any subsystem asking for attention?

### 5.1 Composition

Preferred structure:

```text
+------------------------------------------------------------------+
| TRADE COMPANY CITY                         Healthy / Paper / Time |
|                                                                  |
|                           [CITADEL]                              |
|                    Royal Steward / Supervisor                    |
|                            /                                    |
|                           /  \                                   |
|             [RISK TOWER]      [ARCANE OBSERVATORY]              |
|              Risk Mage          Market Seer                      |
|                    \              /                              |
|                     \            /                               |
|                      [CENTRAL PLAZA]                             |
|             Company health / key city notices                   |
|                     /      |       \                             |
|                    /       |        \                            |
|       [TREASURY]     [TRADING GUILD]     [TAVERN]               |
|       Treasurer       Traders / Board       Bard                 |
|           |                |                  |                  |
|           |         [TRAINING ARENA]          |                  |
|           |                |                  |                  |
|           +--------- [ARCANE NEXUS] ----------+                  |
|                         C.A.O.S                                  |
|                                                                  |
| [SCOUT LODGE / CITY GATE]                 [ARCANE WORKSHOP]      |
| Market Scout / expeditions                 Improvement Manager   |
+------------------------------------------------------------------+
```

This is a conceptual layout, not a fixed pixel-perfect map.

### 5.2 Priority hierarchy

The eye should naturally see:

1. city health / state;
2. Traders / Guild;
3. Treasury;
4. Risk;
5. Market activity;
6. alerts / subsystem attention.

The C.A.O.S Arcane Nexus is visually important but should not obscure the Company-level view.

---

## 6. First-screen HUD

The city view may have a minimal HUD around the illustrated world.

Top-left:

```text
Trade Company
Paper
```

Top-center:

```text
Company Equity
Treasury Reserve
```

Top-right:

```text
City Health
Traders active / effective limit
Alerts
```

The HUD must stay minimal.

The first screen should not become the current card dashboard placed over a fantasy background.

---

## 7. Visual state language

### Healthy

- warm lights;
- normal foot traffic;
- blue/gold magical effects;
- no pulsing warning icons.

### Attention

- amber marker above affected location;
- subtle bell/flare;
- location can be clicked for details.

### Critical

- red marker;
- stronger magical ward;
- city status clearly critical.

### Emergency stop

- city gate closes;
- Risk Tower activates a city-wide barrier;
- Guild expeditions stop;
- persistent emergency banner.

### Offline / stale daemon

- clock tower stopped;
- streets quieter;
- operational pulse absent;
- clear "Operations stopped/stale" indication.

---

## 8. Agent activity visualization

Agents should visually perform the activity represented by their current real state.

Examples:

Market Scout refreshing markets:
- studying map / dispatching falcon.

Risk Mage auditing:
- reading floating runes.

Treasurer allocating capital:
- preparing sealed chest/purse.

Bard processing news:
- listening to patrons / reading messenger note.

Trader ACTIVE:
- working at expedition table or shown outside the guild with assigned market crest.

Trader WAITING:
- studying Quest Board.

Training Arena running experiment:
- tournament animation active.

Improvement Manager with a proposal:
- new glowing research scroll appears.

These animations communicate activity only. They do not trigger backend work merely by playing.

---

## 9. Interaction model

### Hover

Shows a very short tooltip:

```text
Tower of Wards
Risk: Healthy
Drawdown: 1.4%
```

### Single click

Opens the detail drawer/panel for that building or character.

The city remains visible in the background.

### Trader click

Opens the specific Trader detail.

### Quest click

Opens the specific Opportunity detail.

### Alert click

Navigates directly to the responsible location/person.

### Future Drizzt command

A future instruction such as:

```text
"Drizzt, show me why Trade Company is in attention state."
```

should be able to:

1. open Trade Company City;
2. highlight the relevant building;
3. open the corresponding detail panel.

---

## 10. Detail presentation

Details should continue the fantasy metaphor, but always display the real underlying terminology somewhere.

Example:

```text
THE ARCHMAGE OF WARDS
Company Risk Governor

Current Drawdown      2.1%
Gross Exposure        $4.81
Kill Switch           OFF
Reconciliation        OK
```

This prevents the theme from making debugging or operational understanding harder.

Each detail screen contains:

- fantasy title;
- real component/subsystem name;
- plain-language summary;
- operational metrics;
- safe controls;
- technical details tab when needed.

---

## 11. Trader detail example

```text
ADVENTURER A
Trader A

Status             ACTIVE
Quest              BTCUSDT LONG
Tactic             momentum
Capital            $13.42
Current exposure   $1.07

Chosen sizing       8%
Maximum seal       20%

Requested notional $1.07
Maximum allowed    $2.68

[Pause Adventurer]
[View expedition log]
```

The metaphor may label sizing as "chosen commitment" and maximum exposure as "maximum risk seal", but the real financial labels must remain visible.

---

## 12. Treasury detail example

```text
THE GRAND VAULT
Treasury

Reserve                    $12.73
Realized Company Equity    $42.73
Initial Trader allocation  $10.00
Financial spawn capacity   1

Guild capacity
3 / 6 active

Recent ledger
- allocation -> Trader A
- reconciliation -> Trader A
- allocation -> Trader B
...
```

This screen makes the difference between financial capacity and operational capacity immediately visible.

---

## 13. Risk detail example

```text
TOWER OF WARDS
Company Risk Governor

Company Drawdown    1.8%
Gross Exposure      $4.81
Kill Switch         OFF

Trader A
Equity              $13.42
Requested size       8%
Maximum exposure    20%
Current ceiling     $2.68
```

---

## 14. News detail example

```text
THE WHISPERING TANKARD
News / Sentiment

Bard's summary:
"Market conversation is moderately negative..."

Recent messengers
- source
- headline
- timestamp
- sentiment
```

No fabricated "rumors" may be shown unless backed by actual news/sentiment data.

---

## 15. First-screen behavior in standalone mode

Until Drizzt integration exists:

- application opens directly into Trade Company City;
- no kingdom map is required;
- no fake King/Drizzt agent is simulated;
- the Citadel is occupied by the Company Supervisor / Royal Steward;
- the title identifies this as one autonomous Company Cell.

Suggested header:

```text
TRADE COMPANY
Arcane Trading City
Standalone Company Cell
```

Future integration can add:

```text
Return to Kingdom
Ask King Drizzt
```

without redesigning the city.

---

## 16. Future kingdom integration

Once Drizzt supports Company Cells:

```text
Kingdom View
   |
   +-- Trade Company City
   +-- Content Company City
   +-- Sales Company City
   +-- Future Cells
```

Every city should expose a common visual summary:

- health;
- current activity;
- alerts;
- a small set of key metrics;
- last report.

Drizzt should not need knowledge of the internal Trade Company domain to supervise it.

Trade-specific detail remains inside Trade Company City.

---

## 17. Data-to-presentation mapping

The fantasy UI should eventually introduce a dedicated presentation mapper rather than reading raw state everywhere.

Concept:

```text
CompanyControlPort.get_company_status()
            |
            v
CityPresentationMapper
            |
            +-- CityState
            +-- LocationState[]
            +-- CharacterState[]
            +-- AlertMarkers[]
            +-- ActivityAnimations[]
            |
            v
Fantasy City UI
```

Example:

```text
audit.status = "healthy"
    ->
city.mood = "prosperous"

risk.kill_switch = true
    ->
risk_tower.state = "critical"
city.gates = "closed"
city.ward = "active"

Trader A.status = "waiting_assignment"
    ->
Trader A.location = "trading_guild"
Trader A.animation = "studying_quest_board"

treasury_spawn_capacity >= 1
    ->
treasury.ready_funding_chests >= 1
```

This mapper contains presentation semantics only.

---

## 18. Accessibility and operational clarity

The fantasy theme must not make the interface ambiguous.

Every critical state needs:

- visual indicator;
- text label;
- numerical value where applicable.

Do not communicate risk only through color.

Examples:

Bad:

```text
red tower
```

Good:

```text
red tower
+
CRITICAL RISK
+
Drawdown 29.4%
```

The UI should have an optional reduced-animation mode.

---

## 19. What stays outside the fantasy UI

The city must not expose unsafe shortcuts for:

- broker credentials;
- raw broker orders;
- LIVE arming;
- kill-switch reset;
- modifying immutable safety policy without the proper authorization path.

Emergency stop may remain directly visible because it is risk-reducing.

Technical diagnostics may link to the existing C.A.O.S technical dashboard.

---

## 20. First implementation target

The first visual implementation should focus only on the city overview and clickable detail drawers.

Required locations for V1 visual city:

1. Citadel of Oversight — Company Supervisor;
2. Grand Vault — Treasury + Capital Allocator;
3. Tower of Wards — Company Risk Governor + Strategy Diversity;
4. Trading Guild — Traders + Market Allocator + Strategy Registry;
5. Quest Board — Opportunity Registry;
6. Scout Lodge / City Gate — Market Scout;
7. Arcane Observatory — Quant / Market Regime;
8. Whispering Tankard — News / Sentiment;
9. Grand Tournament Arena — Training Arena;
10. Arcane Workshop — Improvement Manager;
11. Arcane Nexus — C.A.O.S;
12. Chronicle Vault — persistence/recovery status, secondary location.

The first implementation does **not** need:

- kingdom map;
- Drizzt avatar;
- other Company cities;
- full 3D movement;
- free-roaming character control;
- gameplay mechanics.

---

## 21. Definition of done for this design goal

This design goal is complete when:

- the fantasy-city concept is formally defined;
- the boundary between theme and backend logic is explicit;
- every current major Trade Company component has a medieval/high-magic visual equivalent;
- C.A.O.S and its specialists have a visual role;
- the first Trade Company City screen has a defined spatial structure;
- health/attention/critical/emergency states have a visual language;
- Trader lifecycle has a visual mapping;
- click-through/detail behavior is defined;
- standalone behavior before Drizzt integration is defined;
- future kingdom/Drizzt integration is accounted for without making it a dependency;
- unsafe execution capabilities remain outside the themed UI.

All items above are defined in this document.

**Goal status: COMPLETE.**
