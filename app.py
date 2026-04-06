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
                "restockingInProgress": False,
                "restockingCyclesRemaining": 0,
                "isLowSeller": False,
                "sellCooldownRemaining": 0,
                "lowSellerRule": None,
                "isHighSeller": False,
                "highSellerRule": None,
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
            restocking_now = state.get("restockingInProgress", False)
            if state["powerState"] == "off":
                # No cooling – warm toward ambient (~25 °C)
                actual += random.uniform(tcfg["powerOffWarmingMin"], tcfg["powerOffWarmingMax"])
            elif restocking_now:
                # Restocking – door wide open for extended time, fast warming
                actual += random.uniform(tcfg.get("restockWarmingMin", 1.2), tcfg.get("restockWarmingMax", 2.5))
            elif state["doorOpen"]:
                # Door open – slow warming (brief customer access)
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
            restocking_in_progress = state.get("restockingInProgress", False)
            restocking_cycles = state.get("restockingCyclesRemaining", 0)

            # ── Active restocking phase (door open, no sales) ────
            if restocking_in_progress:
                if state["powerState"] == "off":
                    # Power out – pause restocking (no filling, close door)
                    state["inventoryLevelPercent"] = round(inv, 1)
                    state["restockCyclesRemaining"] = restock_remaining
                    state["restockingInProgress"] = restocking_in_progress
                    state["restockingCyclesRemaining"] = restocking_cycles
                    state["doorOpen"] = False
                else:
                    restocking_cycles -= 1
                    if restocking_cycles <= 0:
                        # Restocking complete – fill up and resume normal operation
                        inv = icfg["restockFillLevel"]
                        restocking_in_progress = False
                        restocking_cycles = 0
                    else:
                        # Partially fill during restock
                        total_duration = icfg.get("restockDurationCyclesMax", 5)
                        fill_per_cycle = (icfg["restockFillLevel"] - inv) / max(restocking_cycles, 1)
                        inv += fill_per_cycle * random.uniform(0.6, 1.0)
                        inv = min(inv, icfg["restockFillLevel"])

                    state["inventoryLevelPercent"] = round(inv, 1)
                    state["restockCyclesRemaining"] = restock_remaining
                    state["restockingInProgress"] = restocking_in_progress
                    state["restockingCyclesRemaining"] = restocking_cycles

                    # Door is forced open during restock
                    state["doorOpen"] = True

            else:
                # ── Normal operation: sales & restock scheduling ─────

                # Low-seller gate: these freezers only sell once every N cycles
                is_low_seller = state.get("isLowSeller", False)
                sell_cooldown = state.get("sellCooldownRemaining", 0)
                low_rule = state.get("lowSellerRule")
                can_sell = True
                if is_low_seller:
                    if sell_cooldown > 0:
                        sell_cooldown -= 1
                        can_sell = False          # no sale this cycle
                    else:
                        # Sale happens this cycle – reset cooldown for next sale
                        sell_cooldown = random.randint(
                            low_rule["sellIntervalMin"], low_rule["sellIntervalMax"])
                        can_sell = True
                state["sellCooldownRemaining"] = sell_cooldown

                # Resolve per-cycle depletion & bulk-purchase parameters
                is_high_seller = state.get("isHighSeller", False)
                high_rule = state.get("highSellerRule")

                dep_min = high_rule["depletionMin"] if is_high_seller else icfg["depletionMin"]
                dep_max = high_rule["depletionMax"] if is_high_seller else icfg["depletionMax"]
                bulk_prob = high_rule["bulkPurchaseProbability"] if is_high_seller else icfg["bulkPurchaseProbability"]
                # Low sellers with allowBulkPurchase=false never get bulk drops
                allow_bulk = True
                if is_low_seller and not low_rule.get("allowBulkPurchase", True):
                    allow_bulk = False

                if restock_remaining > 0:
                    restock_remaining -= 1
                    if restock_remaining == 0 and state["powerState"] != "off":
                        # Delivery arrived & power is on – begin restocking phase
                        restocking_in_progress = True
                        restocking_cycles = random.randint(
                            icfg.get("restockDurationCyclesMin", 3),
                            icfg.get("restockDurationCyclesMax", 5))
                    # Sales still happen while waiting for delivery
                    if can_sell and inv > 0:
                        inv -= random.uniform(dep_min, dep_max)
                        if allow_bulk and random.random() < bulk_prob:
                            inv -= random.uniform(icfg["bulkPurchaseDropMin"], icfg["bulkPurchaseDropMax"])
                        inv = max(inv, 0.0)
                else:
                    if can_sell and inv > 0:
                        inv -= random.uniform(dep_min, dep_max)
                        if allow_bulk and random.random() < bulk_prob:
                            inv -= random.uniform(icfg["bulkPurchaseDropMin"], icfg["bulkPurchaseDropMax"])
                        inv = max(inv, 0.0)

                if icfg.get("autoRestock", True) and inv < icfg["restockThreshold"] and restock_remaining == 0 and not restocking_in_progress and state["powerState"] != "off":
                    restock_remaining = random.randint(icfg["restockWaitCyclesMin"], icfg["restockWaitCyclesMax"])

                state["inventoryLevelPercent"] = round(inv, 1)
                state["restockCyclesRemaining"] = restock_remaining
                state["restockingInProgress"] = restocking_in_progress
                state["restockingCyclesRemaining"] = restocking_cycles

                # ── Simulate door open / close ───────────────────────
                # Resolve door-open probability: high sellers > default > low sellers
                if inv <= 0:
                    door_prob = 0.0                          # empty freezer – no customers
                elif is_high_seller:
                    door_prob = high_rule.get("doorOpenProbability", icfg["doorOpenProbability"])
                elif is_low_seller:
                    base = low_rule.get("doorOpenProbability", icfg["doorOpenProbability"])
                    # When on cooldown (no active sale), halve the already-low probability
                    door_prob = base * 0.5 if not can_sell else base
                else:
                    door_prob = icfg["doorOpenProbability"]
                state["doorOpen"] = random.random() < door_prob

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
                    freezers[device_id]["restockingInProgress"] = state["restockingInProgress"]
                    freezers[device_id]["restockingCyclesRemaining"] = state["restockingCyclesRemaining"]
                    freezers[device_id]["sellCooldownRemaining"] = state["sellCooldownRemaining"]
                    freezers[device_id]["doorOpen"] = state["doorOpen"]

            if CFG.get("enableLocalJsonOutput", True):
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                file_name = f"{device_id}_{ts}.json"
                file_path = os.path.join(run_dir, file_name)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(message, f, indent=2)

            messages.append(message)

        # Send batch to Event Hub
        if eh_producer and messages and CFG.get("enableEventHub", True):
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

        # ── Apply low-seller rules from config ───────────────────
        for rule in CFG.get("lowSellers", []):
            region_alias = rule["regionAlias"]
            count = rule["count"]
            # Find all freezers in the target region
            candidates = [did for did, f in freezers.items()
                          if did.startswith(region_alias + "-")]
            random.shuffle(candidates)
            for did in candidates[:count]:
                initial_cooldown = random.randint(
                    rule["sellIntervalMin"], rule["sellIntervalMax"])
                freezers[did]["isLowSeller"] = True
                freezers[did]["sellCooldownRemaining"] = initial_cooldown
                freezers[did]["lowSellerRule"] = rule
                print(f"  🐌 {did} marked as low-seller "
                      f"(next sale in {initial_cooldown} cycles)")

        # ── Apply high-seller rules from config ──────────────────
        for rule in CFG.get("highSellers", []):
            region_alias = rule["regionAlias"]
            count = rule["count"]
            candidates = [did for did, f in freezers.items()
                          if did.startswith(region_alias + "-")
                          and not f["isLowSeller"]]
            random.shuffle(candidates)
            for did in candidates[:count]:
                freezers[did]["isHighSeller"] = True
                freezers[did]["highSellerRule"] = rule
                print(f"  🔥 {did} marked as high-seller")

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
