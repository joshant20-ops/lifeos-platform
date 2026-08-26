function formatUptime(seconds) {
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remaining = total % 60;

  return `${hours}h ${minutes}m ${remaining}s`;
}

function formatCurrency(value) {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
  }).format(value);
}

function setText(id, value) {
  const element = document.getElementById(id);

  if (element) {
    element.textContent = value;
  }
}

async function fetchJson(path) {
  const response = await fetch(path, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(
      `${path} returned HTTP ${response.status}`,
    );
  }

  return response.json();
}

async function refreshStatus() {
  const modules = document.getElementById("modules");
  const uptime = document.getElementById("uptime");
  const healthText = document.getElementById("health-text");
  const healthDot = document.querySelector(".health-dot");

  try {
    const data = await fetchJson("/api/status");

    modules.innerHTML = Object.entries(data.modules)
      .map(([name, state]) => {
        const stateClass =
          state === "ready"
            ? "state ready"
            : "state";

        return `
          <div class="module">
            <span>${name.replaceAll("_", " ")}</span>
            <span class="${stateClass}">${state}</span>
          </div>
        `;
      })
      .join("");

    uptime.textContent =
      `Uptime ${formatUptime(data.uptime_seconds)}`;

    healthText.textContent = "Healthy";
    healthDot.classList.add("ready");
  } catch (error) {
    healthText.textContent = "Unavailable";
    uptime.textContent = "Status API unavailable";
    modules.textContent = "Unable to load module state.";
    healthDot.classList.remove("ready");
  }
}

async function refreshSimulation() {
  const targetIds = [
    "solar-total",
    "load-total",
    "import-total",
    "export-total",
    "self-consumption",
    "grid-independence",
    "final-soc",
    "point-count",
  ];

  try {
    const data = await fetchJson("/api/simulation");
    const totals = data.totals;

    setText(
      "solar-total",
      `${totals.solar_generation_kwh.toFixed(2)} kWh`,
    );

    setText(
      "load-total",
      `${totals.household_load_kwh.toFixed(2)} kWh`,
    );

    setText(
      "import-total",
      `${totals.grid_import_kwh.toFixed(2)} kWh`,
    );

    setText(
      "export-total",
      `${totals.grid_export_kwh.toFixed(2)} kWh`,
    );

    setText(
      "self-consumption",
      `${totals.self_consumption_percent.toFixed(1)}%`,
    );

    setText(
      "grid-independence",
      `${totals.grid_independence_percent.toFixed(1)}%`,
    );

    setText(
      "final-soc",
      `${data.final_battery_soc_percent.toFixed(1)}%`,
    );

    setText(
      "point-count",
      `${data.points.length}`,
    );
  } catch (error) {
    targetIds.forEach(
      (id) => setText(id, "Unavailable"),
    );
  }
}

async function refreshCost() {
  const targetIds = [
    "import-cost",
    "export-income",
    "standing-charge",
    "net-daily-cost",
  ];

  try {
    const data = await fetchJson("/api/cost");
    const totals = data.totals;
    const tariff = data.tariff;

    setText(
      "tariff-name",
      `${tariff.name} · ${tariff.import_unit_rate_p_per_kwh}p import · ${tariff.export_unit_rate_p_per_kwh}p export`,
    );

    setText(
      "import-cost",
      formatCurrency(totals.import_cost_gbp),
    );

    setText(
      "export-income",
      formatCurrency(totals.export_income_gbp),
    );

    setText(
      "standing-charge",
      formatCurrency(
        totals.standing_charge_pence / 100,
      ),
    );

    setText(
      "net-daily-cost",
      formatCurrency(totals.net_daily_cost_gbp),
    );
  } catch (error) {
    setText("tariff-name", "Pricing unavailable");

    targetIds.forEach(
      (id) => setText(id, "Unavailable"),
    );
  }
}

refreshStatus();
refreshSimulation();
refreshCost();

setInterval(refreshStatus, 10000);
setInterval(refreshSimulation, 30000);
setInterval(refreshCost, 30000);
