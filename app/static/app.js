"use strict";

// Server values are rendered with textContent only, never as HTML.
const POLL_INTERVAL_MS = 2000;

const view = {
  status: document.getElementById("health-status"),
  database: document.getElementById("health-database"),
  policy: document.getElementById("health-policy"),
  feed: document.getElementById("health-feed"),
  protectedOps: document.getElementById("health-protected"),
  checked: document.getElementById("health-checked"),
};

function versionText(version) {
  return version === null ? "not loaded" : `v${version}`;
}

function renderHealth(health) {
  view.status.textContent = health.status;
  view.status.dataset.state = health.status;
  view.database.textContent = health.database;
  view.policy.textContent = versionText(health.policy_version);
  view.feed.textContent = versionText(health.feed_version);
  view.protectedOps.textContent = health.protected_operations;
}

function renderUnreachable() {
  view.status.textContent = "unreachable";
  view.status.dataset.state = "unreachable";
  for (const field of [view.database, view.policy, view.feed, view.protectedOps]) {
    field.textContent = "unknown";
  }
}

async function refreshHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    renderHealth(await response.json());
  } catch {
    renderUnreachable();
  } finally {
    view.checked.textContent = new Date().toLocaleTimeString();
    setTimeout(refreshHealth, POLL_INTERVAL_MS);
  }
}

refreshHealth();
