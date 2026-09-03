# 🧊 Saving Ice Cream in Real Time

An interactive dashboard that simulates IoT ice-cream freezers, generating controlled telemetry data that mimics real-world device behavior.

## Tech Stack

- **Python 3** + **Flask** — backend API and telemetry engine
- **HTML / CSS / JavaScript** — single-page dashboard (no build step)

## Quick Start

```bash
# Activate the virtual environment
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install dependencies
uv pip install flask

# Run the app
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## Project Structure

```
saving-ice-cream-in-real-time/
├── app.py                        # Flask backend & simulation engine
├── simulation_config.json        # Tunable thresholds for the simulation
├── templates/
│   └── index.html                # Dashboard UI (served by Flask)
├── freezer-telemetry-output/     # Generated telemetry files
│   └── run-YYYY-MM-DD-HHMMSS/   # One folder per simulation run
│       ├── freezer-001_<ts>.json
│       ├── freezer-002_<ts>.json
│       └── ...
└── README.md
```

## Freezer Simulation

The system simulates **25 freezers** (`freezer-001` to `freezer-025`). Each freezer has three configurable properties:

| Property      | Type            | Default   |
|---------------|-----------------|-----------|
| `temperature` | number (°C)     | -20.0     |
| `doorOpen`    | boolean         | false     |
| `powerState`  | `"on"` / `"off"` | `"on"` |

All properties can be changed per-freezer from the dashboard while God Mode is enabled, even while a simulation is running.

## Telemetry Message Format

Each tick produces one JSON file per freezer:

```json
{
  "deviceId": "freezer-001",
  "timestamp": "2026-04-03T22:19:09Z",
  "temperature": -18.5,
  "setPointTemperature": -20.0,
  "doorOpen": false,
  "powerState": "on",
  "sequenceNumber": 42,
  "inventoryLevelPercent": 73.4,
  "messageId": "a3f1c2d4-...",
  "demoRunId": "run-2026-04-03-221500"
}
```

| Field                  | Description                                        |
|------------------------|----------------------------------------------------|
| `deviceId`             | Unique freezer identifier                          |
| `timestamp`            | UTC ISO-8601 timestamp of message creation         |
| `temperature`          | Simulated actual temperature (°C)                  |
| `setPointTemperature`  | Target temperature set in the UI                   |
| `doorOpen`             | Current door state set in the UI                   |
| `powerState`           | Current power state set in the UI                  |
| `sequenceNumber`       | Per-device counter, resets on each new run          |
| `inventoryLevelPercent`| Current stock level (0.0–100.0)                    |
| `messageId`            | Unique UUID generated per message                  |
| `demoRunId`            | Identifier for the simulation run                  |

## File Storage

Telemetry is saved under `freezer-telemetry-output/`, organized by run:

```
freezer-telemetry-output/
  run-2026-04-03-221500/
    freezer-001_20260403T221500123456.json
    freezer-001_20260403T221600654321.json
    freezer-002_20260403T221500234567.json
    ...
```

Each file contains a single JSON message. File names include the device ID and a microsecond-precision UTC timestamp, ensuring uniqueness.

## Dashboard Features

### Freezer Cards

The main area displays a responsive grid of 30 cards — one per freezer. Each card shows:

- **Device ID** — e.g. `freezer-014`
- **Status icon** — ❄️ when powered on, ⚠️ when off
- **Temperature input** — editable number field (°C); changes are sent to the backend immediately
- **Door toggle** — switch to open/close the door
- **Power selector** — dropdown to turn the freezer ON or OFF
- **Sequence counter** — shows the current `sequenceNumber` for the device
- **Inventory bar** — color-coded gauge (green/yellow/red) with percentage and 🚚 restock badge

### God Mode

Expand a freezer's **God Mode** panel and enable its toggle to take manual control of that freezer. While enabled:

- Temperature changes set both the target and actual emitted temperature immediately.
- Door, power, temperature, and inventory remain at the selected values across simulation ticks.
- Automatic sales, restocking, temperature drift, door changes, and regional power outages cannot overwrite the freezer.
- Other freezers continue running automatically.

Disable God Mode to return that freezer to normal simulation behavior. Manual controls are disabled when God Mode is off.

### ▶ Start Simulation

Starts telemetry generation for all freezers. On each start:

- A new `demoRunId` is generated (e.g. `run-2026-04-03-221500`)
- All per-device sequence counters reset to 0
- A background thread begins emitting messages at the configured interval
- The status badge switches to **RUNNING** (green)

### ■ Stop Simulation

Stops the background telemetry thread. No more messages are generated until the next start. The status badge switches to **STOPPED** (red).

### Late-Arrival Simulation

Use **Simulate Late Arrival** to mimic a temporary disconnection between the app and Event Hub:

- While active, telemetry continues to be generated and saved as local JSON, but Event Hub delivery is paused.
- The dashboard shows how many messages are queued for delayed delivery.
- A live `MM:SS` timer shows how long late-arrival mode has been active and remains accurate after a dashboard refresh.
- Select **Resume Event Hub** to send all queued messages before normal delivery resumes.
- Delayed messages retain their original timestamps, sequence numbers, message IDs, and run IDs.

The delayed-message queue is held in application memory. Stopping a simulation does not clear it, but stopping or restarting the Flask process discards any messages that have not been released.

### Interval Configuration

- **Input field** — set the telemetry interval in seconds (minimum: 1)
- **Set button** — applies the new interval; takes effect on the next tick
- Default: **60 seconds**

### Status Indicators

- **Status badge** — green `RUNNING` or red `STOPPED`
- **Run ID** — displays the current `demoRunId` while a simulation is active
- **Late-arrival queue** — displays the number of messages waiting for Event Hub delivery
- **Late-arrival timer** — displays elapsed time since delayed delivery was enabled

## REST API

| Method  | Endpoint                    | Description                          |
|---------|-----------------------------|--------------------------------------|
| `GET`   | `/api/state`                | Full state: all freezers, run info   |
| `PATCH` | `/api/freezer/<device_id>`  | Update a freezer's properties        |
| `PATCH` | `/api/interval`             | Set the telemetry interval           |
| `POST`  | `/api/late-arrival`         | Enable delayed delivery or flush queued messages |
| `POST`  | `/api/start`                | Start a new simulation run           |
| `POST`  | `/api/stop`                 | Stop the current simulation          |

Set late-arrival mode with a JSON body containing `{"active": true}` or `{"active": false}`. The endpoint returns the active state and queued message count. Disabling the mode waits for queued Event Hub messages to flush; if delivery fails, the unsent messages remain queued and the mode stays active.

Set per-freezer God Mode through the freezer PATCH endpoint with `{"godMode": true}` or `{"godMode": false}`. The same request can include `temperature`, `doorOpen`, `powerState`, and `inventoryLevelPercent`.

## Simulation Configuration

All tunable thresholds live in `simulation_config.json`. Edit this file and restart the app to apply changes.

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| *(root)* | `numFreezers` | `25` | Number of simulated freezers |
| *(root)* | `defaultTemperature` | `-20.0` | Initial set-point temperature (°C) |
| *(root)* | `telemetryIntervalSeconds` | `60` | Default telemetry emit interval |
| `temperature` | `powerOffWarmingMin/Max` | `0.5` / `1.0` | Warming rate when power is off |
| `temperature` | `doorOpenWarmingMin/Max` | `0.3` / `0.8` | Warming rate when door is open |
| `temperature` | `compressorCorrectionFactor` | `0.3` | How fast temp tracks toward set-point |
| `temperature` | `noiseMin/Max` | `-0.6` / `0.6` | Random noise band per cycle |
| `inventory` | `initRangeMin/Max` | `40.0` / `100.0` | Default starting inventory range |
| `inventory` | `depletionMin/Max` | `0.1` / `0.7` | Normal per-cycle sales decrease |
| `inventory` | `bulkPurchaseProbability` | `0.05` | Chance of a bulk-purchase spike |
| `inventory` | `bulkPurchaseDropMin/Max` | `5.0` / `10.0` | Extra drop on a bulk purchase |
| `inventory` | `restockThreshold` | `20.0` | Inventory % that triggers a restock |
| `inventory` | `restockFillLevel` | `100.0` | Level inventory jumps to on restock |
| `inventory` | `restockWaitCyclesMin/Max` | `1` / `30` | Delivery delay in telemetry cycles |
| `inventory` | `consoleWarningThreshold` | `20.0` | Print ⚠️ console warning below this % |
| `inventoryStartDistribution` | `lowPercent` | `0.05` | Fraction of freezers starting critically low |
| `inventoryStartDistribution` | `lowRangeMin/Max` | `0.0` / `10.0` | Inventory range for the low group |
| `inventoryStartDistribution` | `midPercent` | `0.05` | Fraction starting in the mid-warning band |
| `inventoryStartDistribution` | `midRangeMin/Max` | `15.0` / `31.0` | Inventory range for the mid group |

## KQL — Eventhouse Table & Ingestion Mapping

### Create table

```kql
.create-merge table IceCreamSaviorTelemetry (
    deviceId: string,
    timestamp: datetime,
    lat: real,
    lon: real,
    temperature: real,
    setPointTemperature: real,
    doorOpen: bool,
    powerState: string,
    sequenceNumber: int,
    inventoryLevelPercent: real,
    messageId: string,
    demoRunId: string
)
```

### Create ingestion mapping

.create-or-alter table IceCreamSaviorTelemetry ingestion json mapping 'IceCreamSaviorTelemetry_mapping'
```
[
  { "column": "deviceId",              "Properties": { "Path": "$['deviceId']" } },
  { "column": "timestamp",             "Properties": { "Path": "$['timestamp']" } },
  { "column": "lat",                   "Properties": { "Path": "$['lat']" } },
  { "column": "lon",                   "Properties": { "Path": "$['lon']" } },
  { "column": "temperature",           "Properties": { "Path": "$['temperature']" } },
  { "column": "setPointTemperature",   "Properties": { "Path": "$['setPointTemperature']" } },
  { "column": "doorOpen",              "Properties": { "Path": "$['doorOpen']" } },
  { "column": "powerState",            "Properties": { "Path": "$['powerState']" } },
  { "column": "sequenceNumber",        "Properties": { "Path": "$['sequenceNumber']" } },
  { "column": "inventoryLevelPercent", "Properties": { "Path": "$['inventoryLevelPercent']" } },
  { "column": "messageId",             "Properties": { "Path": "$['messageId']" } },
  { "column": "demoRunId",             "Properties": { "Path": "$['demoRunId']" } }
]
```
