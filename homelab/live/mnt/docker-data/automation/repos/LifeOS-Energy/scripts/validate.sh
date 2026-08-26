#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/mnt/docker-data/automation/repos/LifeOS-Energy"
cd "${ROOT}"

echo "[validate] Git branch"
test "$(git branch --show-current)" = "develop"

echo "[validate] Python syntax"
python3 -m compileall -q app tests

echo "[validate] Host configuration loader"
python3 - <<'PYTHON'
from app.config import load_config

config = load_config()

assert config["application"]["name"] == "LifeOS Energy"
assert config["site"]["timezone"] == "Europe/London"
assert config["energy"]["battery_capacity_kwh"] > 0
assert config["tariff"]["import_unit_rate_p_per_kwh"] >= 0
assert config["tariff"]["export_unit_rate_p_per_kwh"] >= 0
assert config["tariff"]["standing_charge_p_per_day"] >= 0

print("Host configuration loader valid")
PYTHON

echo "[validate] YAML configuration"
python3 - <<'PYTHON'
from pathlib import Path
import yaml

config = yaml.safe_load(
    Path("config/config.yaml").read_text(
        encoding="utf-8"
    )
)

required = {
    "application",
    "site",
    "energy",
    "tariff",
    "logging",
}

assert required.issubset(config)

print("YAML valid")
PYTHON

echo "[validate] Simulator"
python3 - <<'PYTHON'
from app.config import load_config
from app.services.simulator import run_daily_simulation

config = load_config()
result = run_daily_simulation(config)

assert result["model"] == "deterministic_v1"
assert len(result["points"]) == 24
assert result["totals"]["solar_generation_kwh"] > 0
assert result["totals"]["household_load_kwh"] > 0

for point in result["points"]:
    assert (
        config["energy"]["battery_minimum_percent"]
        <= point["battery_soc_percent"]
        <= config["energy"]["battery_maximum_percent"]
    )

print("Simulator valid")
print(result["totals"])
PYTHON

echo "[validate] Pricing engine"
python3 - <<'PYTHON'
from app.config import load_config
from app.services.pricing import calculate_daily_cost
from app.services.simulator import run_daily_simulation

config = load_config()
simulation = run_daily_simulation(config)

result = calculate_daily_cost(
    simulation,
    config["tariff"],
)

assert result["model"] == "fixed_tariff_v1"
assert len(result["points"]) == 24

totals = result["totals"]

assert totals["import_cost_pence"] >= 0
assert totals["export_income_pence"] >= 0
assert totals["standing_charge_pence"] >= 0

expected = round(
    totals["net_energy_cost_pence"]
    + totals["standing_charge_pence"],
    2,
)

assert totals["net_daily_cost_pence"] == expected

print("Pricing engine valid")
print(totals)
PYTHON

echo "[validate] Pricing regression example"
python3 - <<'PYTHON'
from app.services.pricing import calculate_daily_cost

simulation = {
    "points": [
        {
            "hour": 0,
            "grid_import_kw": 2.0,
            "grid_export_kw": 0.0,
        },
        {
            "hour": 1,
            "grid_import_kw": 0.0,
            "grid_export_kw": 1.5,
        },
    ]
}

tariff = {
    "name": "Validation Tariff",
    "provider": "validation",
    "import_unit_rate_p_per_kwh": 25.0,
    "export_unit_rate_p_per_kwh": 10.0,
    "standing_charge_p_per_day": 50.0,
}

result = calculate_daily_cost(
    simulation,
    tariff,
)

assert result["totals"]["import_cost_pence"] == 50.0
assert result["totals"]["export_income_pence"] == 15.0
assert result["totals"]["net_daily_cost_pence"] == 85.0

print("Pricing regression valid")
PYTHON

echo "[validate] Dashboard source files"
test -s templates/index.html
test -s static/app.css
test -s static/app.js

grep -q "Modelled daily cost" templates/index.html
grep -q "refreshCost" static/app.js
grep -q "emphasised-panel" static/app.css

echo "[validate] Docker Compose"
docker compose config --quiet

echo "[validate] Container state"
docker compose ps

CONTAINER_STATUS="$(
  docker inspect     --format '{{.State.Status}}'     lifeos-energy
)"

CONTAINER_HEALTH="$(
  docker inspect     --format '{{.State.Health.Status}}'     lifeos-energy
)"

test "${CONTAINER_STATUS}" = "running"
test "${CONTAINER_HEALTH}" = "healthy"

echo "[validate] Health API"
curl   --fail   --silent   --show-error   http://127.0.0.1:8110/health
echo

echo "[validate] Status API"
STATUS_JSON="$(
  curl     --fail     --silent     --show-error     http://127.0.0.1:8110/api/status
)"

python3 - "${STATUS_JSON}" <<'PYTHON'
import json
import sys

payload = json.loads(sys.argv[1])

assert payload["modules"]["simulation"] == "ready"
assert payload["modules"]["pricing"] == "ready"
assert payload["modules"]["optimiser"] == "planned"

print(
    json.dumps(
        payload["modules"],
        indent=2,
    )
)
PYTHON

echo "[validate] Simulation API"
SIMULATION_JSON="$(
  curl     --fail     --silent     --show-error     http://127.0.0.1:8110/api/simulation
)"

python3 - "${SIMULATION_JSON}" <<'PYTHON'
import json
import sys

payload = json.loads(sys.argv[1])

assert payload["model"] == "deterministic_v1"
assert len(payload["points"]) == 24

print(
    json.dumps(
        payload["totals"],
        indent=2,
    )
)
PYTHON

echo "[validate] Cost API"
COST_JSON="$(
  curl     --fail     --silent     --show-error     http://127.0.0.1:8110/api/cost
)"

python3 - "${COST_JSON}" <<'PYTHON'
import json
import sys

payload = json.loads(sys.argv[1])

assert payload["model"] == "fixed_tariff_v1"
assert len(payload["points"]) == 24

required = {
    "import_cost_pence",
    "export_income_pence",
    "net_energy_cost_pence",
    "standing_charge_pence",
    "net_daily_cost_pence",
    "import_cost_gbp",
    "export_income_gbp",
    "net_daily_cost_gbp",
}

assert required.issubset(payload["totals"])

print(
    json.dumps(
        payload["totals"],
        indent=2,
    )
)
PYTHON

echo "[validate] Dashboard HTML"
curl   --fail   --silent   --show-error   http://127.0.0.1:8110/   | grep -q "Modelled daily cost"

echo "[validate] Static JavaScript"
curl   --fail   --silent   --show-error   http://127.0.0.1:8110/static/app.js   | grep -q "refreshCost"

echo "[validate] Persistent log"
test -s logs/lifeos-energy.log

tail -n 12 logs/lifeos-energy.log

grep -q "pricing_ready" logs/lifeos-energy.log

echo "VALIDATION PASSED"
