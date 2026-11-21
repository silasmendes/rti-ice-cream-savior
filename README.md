# 🧊 Saving Ice Cream in Real Time

An interactive dashboard that simulates IoT ice-cream freezers, generating controlled telemetry data that mimics real-world device behavior.

This project is primarily designed as a hands-on learning resource for classes about Microsoft Fabric Real-Time Intelligence.

## Tech Stack

- **Python 3** + **Flask** — backend API and telemetry engine
- **HTML / CSS / JavaScript** — single-page dashboard

## Quick Start

```bash
# Activate the virtual environment
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install dependencies
python -m pip install -r requirements.txt

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

### Pause Event Delivery

Select **Pause Event Delivery** to hold new telemetry events in memory instead of sending them to Event Hub:

- Telemetry generation continues while the simulation is running. Local JSON files are saved only when `enableLocalJsonOutput` is enabled.
- The dashboard shows the number of queued events and a live `MM:SS` pause timer that remains accurate after a dashboard refresh.
- Select **Resume & Send Queued Events** to send the queue in batches before normal delivery resumes.
- Queued events retain their original timestamps, sequence numbers, message IDs, and run IDs.
- If sending fails, remaining events stay queued so you can retry.

This pauses publishing; it does not disconnect the network, deliberately reorder events, or configure downstream handling of late events. Event Hub must be configured and enabled to pause delivery.

The queue is held in application memory. Stopping the simulation preserves it, but stopping or restarting the Flask process discards any events that have not been sent.

### Status Indicators

- **Status badge** — green `RUNNING` or red `STOPPED`
- **Run ID** — displays the current `demoRunId` while a simulation is active
- **Queued events** — displays the number of messages waiting for Event Hub delivery
- **Delivery pause timer** — displays elapsed time since event delivery was paused

## Choose Event Hubs authentication

Copy `.env.example` to `.env` if you do not already have one. Choose authentication with **one setting**, `EVENT_HUB_AUTH_MODE`:

| Mode | Required settings | Sign-in |
|------|-------------------|---------|
| `connection_string` (default) | `EVENT_HUB_NAME`, `EVENT_HUB_CONNECTION_STRING` | SAS key in the connection string |
| `azure_cli` | `EVENT_HUB_NAME`, `EVENT_HUB_FULLY_QUALIFIED_NAMESPACE` | Your Entra account through `az login` |

You can keep both sets of values in `.env` and switch only `EVENT_HUB_AUTH_MODE` when the destination Event Hub is the same. Update `EVENT_HUB_NAME` too when changing destinations. The inactive mode's credentials are ignored; the app never falls back to another mode after an authentication failure.

**Stop and restart the Flask process after editing `.env`.** Stopping and starting the simulation in the dashboard does not reload authentication. Existing terminal environment variables take precedence over `.env` values. At startup, the app prints the selected mode and Event Hub name, without credentials.

### SAS key / connection string

1. In Azure Portal, open your Event Hubs namespace or Event Hub and select **Shared access policies**. Use a policy with **Send** permission and copy its complete **Connection string–primary key** or secondary connection string.
2. Configure `.env`:

   ```dotenv
   EVENT_HUB_AUTH_MODE=connection_string
   EVENT_HUB_NAME=<event-hub-name>
   EVENT_HUB_CONNECTION_STRING="Endpoint=sb://<namespace>.servicebus.windows.net/;SharedAccessKeyName=<policy-name>;SharedAccessKey=<key>"
   ```

   Paste the complete connection string, not just the key. Namespace connection strings work because the app supplies `EVENT_HUB_NAME` separately. If the connection string includes `EntityPath`, use the same Event Hub name in `EVENT_HUB_NAME`.

3. Restart `python app.py` and start the simulation. No Azure CLI login is needed in this mode.

SAS/local authentication must be enabled on the namespace and permitted by your organization's policies. Switching this setting cannot bypass a policy that disables SAS. See [Microsoft's SAS documentation](https://learn.microsoft.com/en-us/azure/event-hubs/authenticate-shared-access-signature).

### Entra account / Azure CLI

1. In Azure Portal, open your Event Hub (or its namespace), select **Access control (IAM)**, and assign your user **Azure Event Hubs Data Sender**. An administrator with role assignment permissions may need to do this. Management roles such as Contributor alone do not grant permission to send events.
2. Install [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) and install the Python dependencies with `python -m pip install -r requirements.txt`.
3. Sign in to the tenant that owns the Event Hubs namespace:

   ```powershell
   az login --tenant <tenant-id>
   az account set --subscription <subscription-id>
   ```

   On Windows, if `az` is not recognized after installation, fully restart your IDE. For the current PowerShell terminal, the default 64-bit installation can be added with:

   ```powershell
   $env:Path = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin;" + $env:Path
   ```

4. Configure `.env`:

   ```dotenv
   EVENT_HUB_AUTH_MODE=azure_cli
   EVENT_HUB_FULLY_QUALIFIED_NAMESPACE=rgehssm001.servicebus.windows.net
   EVENT_HUB_NAME=evh001
   ```

   Use your actual namespace hostname and Event Hub name. This mode uses `AzureCliCredential` and ignores `EVENT_HUB_CONNECTION_STRING`. It supports namespaces where SAS/local authentication is disabled. No password or access token belongs in `.env`.

5. Restart `python app.py` from a terminal where `az` is available and start the simulation. New role assignments can take several minutes to propagate. If the CLI session expires, run `az login` again.

This mode is for local development using your signed-in account. For an unattended Azure deployment, use a managed identity instead of a personal CLI session.

See [Microsoft's Entra authorization documentation](https://learn.microsoft.com/en-us/azure/event-hubs/authenticate-application).

## Send Telemetry to a Fabric Eventstream

Use `EVENT_HUB_AUTH_MODE=connection_string` (the default) for the SAS configuration below.

1. In a Fabric workspace, create a new **Eventstream**.
2. Add a **Custom Endpoint** as a source, then publish the eventstream.
3. Switch to **Live mode** and select the Custom Endpoint source. In the **Details** section, select the **Kafka** option.
4. In the Kafka settings, select **SAS Key Authentication**.
5. Copy the **Topic name** value and add it to your `.env` file as `EVENT_HUB_NAME`:

   ```dotenv
   EVENT_HUB_NAME=<topic-name>
   ```

6. Copy the **Connection string-primary key** value and add it to your `.env` file as `EVENT_HUB_CONNECTION_STRING`:

   ```dotenv
   EVENT_HUB_CONNECTION_STRING=<connection-string-primary-key>
   ```

7. Save the `.env` file and start the server:

   ```bash
   python app.py
   ```

8. Open **http://127.0.0.1:5000** in a web browser and start the simulation.
9. Return to the Fabric Eventstream page and select the **Eventstream** node immediately after the Custom Endpoint source. Select **Data Preview** to monitor telemetry ingestion.

## KQL — Eventhouse Table & Ingestion Mapping

To send the telemetry to a Fabric Eventhouse, use the following KQL commands to create the destination table and its ingestion mapping.

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

## Simulation Configuration

All tunable thresholds live in `simulation_config.json`. Edit this file and restart the app to apply changes.

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| *(root)* | `numFreezers` | `4` | Number of simulated freezers |
| *(root)* | `defaultTemperature` | `-20.0` | Initial set-point temperature (°C) |
| *(root)* | `telemetryIntervalSeconds` | `30` | Default telemetry emit interval |
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
| `inventory` | `restockWaitCyclesMin/Max` | `1` / `10` | Delivery delay in telemetry cycles |
| `inventory` | `consoleWarningThreshold` | `20.0` | Print ⚠️ console warning below this % |
| `inventoryStartDistribution` | `lowPercent` | `0.10` | Fraction of freezers starting critically low |
| `inventoryStartDistribution` | `lowRangeMin/Max` | `0.0` / `10.0` | Inventory range for the low group |
| `inventoryStartDistribution` | `midPercent` | `0.20` | Fraction starting in the mid-warning band |
| `inventoryStartDistribution` | `midRangeMin/Max` | `15.0` / `31.0` | Inventory range for the mid group |
