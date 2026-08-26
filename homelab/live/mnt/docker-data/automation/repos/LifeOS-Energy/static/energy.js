
"use strict";

const elements = {
  production: document.getElementById("production"),
  consumption: document.getElementById("consumption"),
  grid: document.getElementById("grid"),
  gridDirection: document.getElementById("grid-direction"),
  batterySoc: document.getElementById("battery-soc"),
  batteryPower: document.getElementById("battery-power"),
  stateDot: document.getElementById("state-dot"),
  stateText: document.getElementById("state-text"),
  source: document.getElementById("source"),
  updated: document.getElementById("updated"),
  historyCount: document.getElementById("history-count"),
  canvas: document.getElementById("history-chart"),
  powerdownStatus: document.getElementById("powerdown-status"),
  powerdownReason: document.getElementById("powerdown-reason"),
};

function watts(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const absolute = Math.abs(value);

  if (absolute >= 1000) {
    return `${(value / 1000).toFixed(2)} kW`;
  }

  return `${Math.round(value)} W`;
}

function setState(state, healthy) {
  elements.stateText.textContent = state;
  elements.stateDot.classList.toggle("live", healthy);
}

async function fetchJson(url) {
  const response = await fetch(url, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json();
}

function renderCurrent(data) {
  elements.production.textContent = watts(data.production_w);
  elements.consumption.textContent = watts(data.consumption_w);

  if (data.grid_import_w > 0) {
    elements.grid.textContent = watts(data.grid_import_w);
    elements.gridDirection.textContent = "Importing";
  } else {
    elements.grid.textContent = watts(data.grid_export_w);
    elements.gridDirection.textContent = "Exporting";
  }

  const battery = data.battery || {};

  elements.batterySoc.textContent =
    battery.soc_percent === null ||
    battery.soc_percent === undefined
      ? "—"
      : `${battery.soc_percent.toFixed(0)}%`;

  if (battery.power_w === null || battery.power_w === undefined) {
    elements.batteryPower.textContent = "Power unavailable";
  } else {
    elements.batteryPower.textContent =
      `${watts(battery.power_w)} battery flow`;
  }

  setState(data.state || "LIVE", data.state === "LIVE");
  elements.source.textContent =
    `Source: ${data.provider || data.source || "unknown"}`;

  elements.updated.textContent =
    `Updated: ${new Date(data.retrieved_at * 1000).toLocaleTimeString()}`;
}

function seriesRange(points) {
  const values = [];

  for (const point of points) {
    for (const key of [
      "production_w",
      "consumption_w",
      "grid_import_w",
      "battery_power_w",
    ]) {
      const value = point[key];

      if (typeof value === "number") {
        values.push(value);
      }
    }
  }

  if (!values.length) {
    return {min: 0, max: 1};
  }

  let min = Math.min(...values, 0);
  let max = Math.max(...values, 1);

  if (min === max) {
    max += 1;
  }

  return {min, max};
}

function renderHistory(payload) {
  const points = payload.points || [];
  const canvas = elements.canvas;
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const padding = 44;

  context.clearRect(0, 0, width, height);
  elements.historyCount.textContent =
    `${payload.count || 0} readings`;

  if (points.length < 2) {
    context.font = "24px sans-serif";
    context.textAlign = "center";
    context.fillText(
      "History will appear as readings are collected",
      width / 2,
      height / 2,
    );
    return;
  }

  const range = seriesRange(points);
  const firstTime = points[0].reading_time;
  const lastTime = points[points.length - 1].reading_time;
  const timeSpan = Math.max(lastTime - firstTime, 1);

  function xFor(point) {
    return padding +
      ((point.reading_time - firstTime) / timeSpan) *
      (width - padding * 2);
  }

  function yFor(value) {
    return height - padding -
      ((value - range.min) / (range.max - range.min)) *
      (height - padding * 2);
  }

  context.lineWidth = 1;
  context.globalAlpha = 0.2;
  context.beginPath();
  context.moveTo(padding, yFor(0));
  context.lineTo(width - padding, yFor(0));
  context.stroke();
  context.globalAlpha = 1;

  const series = [
    "production_w",
    "consumption_w",
    "grid_import_w",
    "battery_power_w",
  ];

  series.forEach((key, index) => {
    context.beginPath();
    context.lineWidth = index === 0 ? 4 : 2;

    let started = false;

    for (const point of points) {
      const value = point[key];

      if (typeof value !== "number") {
        continue;
      }

      const x = xFor(point);
      const y = yFor(value);

      if (!started) {
        context.moveTo(x, y);
        started = true;
      } else {
        context.lineTo(x, y);
      }
    }

    context.stroke();
  });
}

async function refreshCurrent() {
  try {
    const data = await fetchJson("/api/energy/current");
    renderCurrent(data);
  } catch (error) {
    setState("OFFLINE", false);
    elements.updated.textContent = `Error: ${error.message}`;
  }
}

async function refreshHistory() {
  try {
    const data = await fetchJson("/api/energy/history?hours=24");
    renderHistory(data);
  } catch (error) {
    elements.historyCount.textContent = "History unavailable";
  }
}


function formatPowerDownDecision(decision) {
  const labels = {
    WAITING_FOR_EVENT: "Waiting for event",
    EVENT_AVAILABLE: "Event available",
    JOINED: "Joined",
    ACTIVE: "Active",
    COMPLETE: "Complete",
    COMPLETED: "Complete",
    NOT_JOINED: "Not joined",
    UNAVAILABLE: "Unavailable",
  };

  if (!decision) {
    return "Unavailable";
  }

  if (labels[decision]) {
    return labels[decision];
  }

  return decision
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

async function refreshPowerDown() {
  try {
    const data = await fetchJson("/api/energy/powerdown");

    elements.powerdownStatus.textContent =
      formatPowerDownDecision(data.decision);

    elements.powerdownReason.textContent =
      data.reason || "No additional information";

    elements.powerdownStatus.title =
      data.decision_at
        ? `Decision updated ${new Date(data.decision_at).toLocaleString()}`
        : "";
  } catch (error) {
    elements.powerdownStatus.textContent = "Unavailable";
    elements.powerdownReason.textContent =
      `Power Down status error: ${error.message}`;
  }
}

async function start() {
  await Promise.all([
    refreshCurrent(),
    refreshHistory(),
    refreshPowerDown(),
  ]);

  window.setInterval(refreshCurrent, 5000);
  window.setInterval(refreshHistory, 60000);
  window.setInterval(refreshPowerDown, 60000);
}

start();
