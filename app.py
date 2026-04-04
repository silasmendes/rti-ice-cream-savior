import json
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone

from azure.eventhub import EventHubProducerClient, EventData
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

# ── Event Hub client ────────────────────────────────────────────────
EVENT_HUB_CONNECTION_STRING = os.getenv("EVENT_HUB_CONNECTION_STRING")
EVENT_HUB_NAME = os.getenv("EVENT_HUB_NAME")

eh_producer = None
if EVENT_HUB_CONNECTION_STRING and EVENT_HUB_NAME:
    eh_producer = EventHubProducerClient.from_connection_string(
        conn_str=EVENT_HUB_CONNECTION_STRING,
        eventhub_name=EVENT_HUB_NAME,
    )

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "freezer-telemetry-output")

# ── Load simulation config ──────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "simulation_config.json")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as _cf:
        return json.load(_cf)

CFG = load_config()


def build_freezers(cfg):
    """Create a fresh freezers dict from the given config, distributed across regions."""
    regions = cfg["regions"]
    num_freezers = cfg["numFreezers"]

    # ── Weight normalization ────────────────────────────────
    total_weight = sum(r["weight"] for r in regions)
    for r in regions:
        r["_norm_weight"] = r["weight"] / total_weight

    # ── Allocate freezers per region (handle rounding) ──────
    alloc = []
    for r in regions:
        alloc.append(int(num_freezers * r["_norm_weight"]))
    remainder = num_freezers - sum(alloc)
    # Distribute remainder to last region
    alloc[-1] += remainder

    # ── Build devices ───────────────────────────────────────
    result = {}
    for idx, region in enumerate(regions):
        count = alloc[idx]
        print(f"  {region['name']}: {count} freezers initialized")
        for i in range(1, count + 1):
            device_id = f"{region['alias']}-{i:02d}"
            jitter_lat = random.uniform(-0.0005, 0.0005)
            jitter_lon = random.uniform(-0.0005, 0.0005)
            result[device_id] = {
                "deviceId": device_id,
                "lat": round(region["lat"] + jitter_lat, 6),
                "lon": round(region["lon"] + jitter_lon, 6),
                "region": region["name"],
                "temperature": cfg["defaultTemperature"],
                "actualTemperature": cfg["defaultTemperature"],
                "doorOpen": False,
                "powerState": "on",
                "sequenceNumber": 0,
                "inventoryLevelPercent": round(random.uniform(
                    cfg["inventory"]["initRangeMin"],
                    cfg["inventory"]["initRangeMax"]), 1),
                "restockCyclesRemaining": 0,
            }
    return result


# ── Simulation state ────────────────────────────────────────────────
freezers = build_freezers(CFG)

sim_lock = threading.Lock()
sim_running = False
sim_thread = None
sim_interval = CFG["telemetryIntervalSeconds"]
demo_run_id = None


def generate_telemetry():
    """Background thread that emits telemetry at the configured interval."""
    global sim_running
    while True:
        with sim_lock:
            if not sim_running:
                break
            current_interval = sim_interval
            run_id = demo_run_id
            snapshot = {did: dict(f) for did, f in freezers.items()}

        run_dir = os.path.join(OUTPUT_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)

        messages = []
        for device_id, state in snapshot.items():
            state["sequenceNumber"] += 1

            # ── Simulate realistic temperature fluctuation ───────
            target = state["temperature"]
            actual = state["actualTemperature"]

            tcfg = CFG["temperature"]
            if state["powerState"] == "off":
                # No cooling – warm toward ambient (~25 °C)
                actual += random.uniform(tcfg["powerOffWarmingMin"], tcfg["powerOffWarmingMax"])
            elif state["doorOpen"]:
                # Door open – slow warming
                actual += random.uniform(tcfg["doorOpenWarmingMin"], tcfg["doorOpenWarmingMax"])
            else:
                # Normal compressor cycle – drift toward set point ± noise
                diff = target - actual
                actual += diff * tcfg["compressorCorrectionFactor"] + random.uniform(tcfg["noiseMin"], tcfg["noiseMax"])

            state["actualTemperature"] = round(actual, 1)

            # ── Simulate inventory depletion & restocking ────────
            icfg = CFG["inventory"]
            inv = state["inventoryLevelPercent"]
            restock_remaining = state["restockCyclesRemaining"]

            if restock_remaining > 0:
                restock_remaining -= 1
                if restock_remaining == 0:
                    inv = icfg["restockFillLevel"]
                else:
                    if inv > 0:
                        inv -= random.uniform(icfg["depletionMin"], icfg["depletionMax"])
                        if random.random() < icfg["bulkPurchaseProbability"]:
                            inv -= random.uniform(icfg["bulkPurchaseDropMin"], icfg["bulkPurchaseDropMax"])
                        inv = max(inv, 0.0)
            else:
                if inv > 0:
                    inv -= random.uniform(icfg["depletionMin"], icfg["depletionMax"])
                    if random.random() < icfg["bulkPurchaseProbability"]:
                        inv -= random.uniform(icfg["bulkPurchaseDropMin"], icfg["bulkPurchaseDropMax"])
                    inv = max(inv, 0.0)

            if icfg.get("autoRestock", True) and inv < icfg["restockThreshold"] and restock_remaining == 0:
                restock_remaining = random.randint(icfg["restockWaitCyclesMin"], icfg["restockWaitCyclesMax"])

            state["inventoryLevelPercent"] = round(inv, 1)
            state["restockCyclesRemaining"] = restock_remaining

            if inv < icfg["consoleWarningThreshold"]:
                print(f"\033[91m⚠️  {device_id} inventory LOW: {state['inventoryLevelPercent']}%"
                      f"  (restock in {restock_remaining} cycles)\033[0m")

            message = {
                "deviceId": device_id,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lat": state["lat"],
                "lon": state["lon"],
                "temperature": state["actualTemperature"],
                "setPointTemperature": target,
                "doorOpen": state["doorOpen"],
                "powerState": state["powerState"],
                "sequenceNumber": state["sequenceNumber"],
                "inventoryLevelPercent": state["inventoryLevelPercent"],
                "messageId": str(uuid.uuid4()),
                "demoRunId": run_id,
            }

            # Persist updated state back
            with sim_lock:
                if device_id in freezers:
                    freezers[device_id]["sequenceNumber"] = state["sequenceNumber"]
                    freezers[device_id]["actualTemperature"] = state["actualTemperature"]
                    freezers[device_id]["inventoryLevelPercent"] = state["inventoryLevelPercent"]
                    freezers[device_id]["restockCyclesRemaining"] = state["restockCyclesRemaining"]

            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            file_name = f"{device_id}_{ts}.json"
            file_path = os.path.join(run_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(message, f, indent=2)

            messages.append(message)

        # Send batch to Event Hub
        if eh_producer and messages:
            try:
                batch = eh_producer.create_batch()
                for msg in messages:
                    batch.add(EventData(json.dumps(msg)))
                eh_producer.send_batch(batch)
                print(f"[EventHub] Sent {len(messages)} events")
            except Exception as exc:
                print(f"[EventHub] Error sending batch: {exc}")

        # Sleep in small increments so we can stop quickly
        elapsed = 0.0
        while elapsed < current_interval:
            time.sleep(min(0.5, current_interval - elapsed))
            elapsed += 0.5
            with sim_lock:
                if not sim_running:
                    return


# ── Routes ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def get_state():
    with sim_lock:
        return jsonify(
            {
                "freezers": list(freezers.values()),
                "running": sim_running,
                "interval": sim_interval,
                "demoRunId": demo_run_id,
            }
        )


@app.route("/api/freezer/<device_id>", methods=["PATCH"])
def update_freezer(device_id):
    with sim_lock:
        if device_id not in freezers:
            return jsonify({"error": "Unknown device"}), 404
        data = request.get_json(force=True)
        if "temperature" in data:
            freezers[device_id]["temperature"] = float(data["temperature"])
        if "doorOpen" in data:
            freezers[device_id]["doorOpen"] = bool(data["doorOpen"])
        if "powerState" in data:
            freezers[device_id]["powerState"] = data["powerState"]
        if "inventoryLevelPercent" in data:
            freezers[device_id]["inventoryLevelPercent"] = round(
                max(0.0, min(100.0, float(data["inventoryLevelPercent"]))), 1)
        return jsonify(freezers[device_id])


@app.route("/api/power-outage", methods=["POST"])
def power_outage():
    data = request.get_json(force=True)
    state = "off" if data.get("outage") else "on"
    with sim_lock:
        for f in freezers.values():
            f["powerState"] = state
    return jsonify({"powerState": state})


@app.route("/api/interval", methods=["PATCH"])
def set_interval():
    global sim_interval
    data = request.get_json(force=True)
    val = int(data.get("interval", 60))
    if val < 1:
        return jsonify({"error": "Interval must be >= 1"}), 400
    with sim_lock:
        sim_interval = val
    return jsonify({"interval": sim_interval})


@app.route("/api/start", methods=["POST"])
def start_simulation():
    global sim_running, sim_thread, demo_run_id, CFG, freezers, sim_interval
    with sim_lock:
        if sim_running:
            return jsonify({"error": "Already running"}), 409

        # Reload config from disk so edits take effect without restarting
        CFG = load_config()
        print("\n🧊 Initializing freezers by region:")
        freezers = build_freezers(CFG)
        sim_interval = CFG["telemetryIntervalSeconds"]

        # Apply start distribution
        dist = CFG["inventoryStartDistribution"]
        device_ids = list(freezers.keys())
        random.shuffle(device_ids)
        n = len(device_ids)
        n_low = max(1, round(n * dist["lowPercent"]))
        n_mid = max(1, round(n * dist["midPercent"]))
        low_ids = set(device_ids[:n_low])
        mid_ids = set(device_ids[n_low:n_low + n_mid])

        for did, f in freezers.items():
            if did in low_ids:
                f["inventoryLevelPercent"] = round(random.uniform(dist["lowRangeMin"], dist["lowRangeMax"]), 1)
            elif did in mid_ids:
                f["inventoryLevelPercent"] = round(random.uniform(dist["midRangeMin"], dist["midRangeMax"]), 1)

        now = datetime.now(timezone.utc)
        demo_run_id = f"run-{now.strftime('%Y-%m-%d')}-{now.strftime('%H%M%S')}"
        sim_running = True

    sim_thread = threading.Thread(target=generate_telemetry, daemon=True)
    sim_thread.start()
    return jsonify({"demoRunId": demo_run_id})


@app.route("/api/stop", methods=["POST"])
def stop_simulation():
    global sim_running
    with sim_lock:
        sim_running = False
    if sim_thread:
        sim_thread.join(timeout=5)
    return jsonify({"stopped": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
