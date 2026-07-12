export function filterDashboards(items, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) => (
    `${item?.name || ""} ${item?.model || ""}`.toLowerCase().includes(needle)
  ));
}

export const DASHBOARD_REFRESH_OPTIONS = Object.freeze([
  { value: 0, label: "Off" },
  { value: 30000, label: "Every 30 seconds" },
  { value: 60000, label: "Every minute" },
  { value: 300000, label: "Every 5 minutes" },
]);

const DASHBOARD_REFRESH_VALUES = new Set(DASHBOARD_REFRESH_OPTIONS.map((option) => option.value));

export function normalizeDashboardRefreshMs(value) {
  const milliseconds = Number(value);
  return DASHBOARD_REFRESH_VALUES.has(milliseconds) ? milliseconds : 0;
}

export function shouldRunScheduledDashboardRefresh(visibilityState, requestPending) {
  return visibilityState === "visible" && !requestPending;
}

export function createSerialDashboardQueue() {
  let tail = Promise.resolve();
  let pending = 0;
  return {
    enqueue(task) {
      pending += 1;
      const result = tail.then(() => task());
      tail = result.then(() => undefined, () => undefined).finally(() => { pending -= 1; });
      return result;
    },
    isBusy() {
      return pending > 0;
    },
    whenIdle() {
      return tail;
    },
  };
}

function widgetFingerprint(widget) {
  return JSON.stringify([
    widget?.connection_id || widget?.connection || "",
    widget?.type || "",
    widget?.title || "",
    widget?.sql || "",
  ]);
}

function shortHash(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return (hash >>> 0).toString(36);
}

export function reconcileDashboardWidgets(incoming, current = [], preserveCurrentOrder = true) {
  if (!Array.isArray(incoming)) return [];
  const previousByFingerprint = new Map();
  for (const widget of Array.isArray(current) ? current : []) {
    if (!widget?._clientKey) continue;
    const fingerprint = widgetFingerprint(widget);
    const matches = previousByFingerprint.get(fingerprint) || [];
    matches.push(widget._clientKey);
    previousByFingerprint.set(fingerprint, matches);
  }

  const occurrences = new Map();
  const usedKeys = new Set();
  const keyed = incoming.map((widget) => {
    const fingerprint = widgetFingerprint(widget);
    const occurrence = occurrences.get(fingerprint) || 0;
    occurrences.set(fingerprint, occurrence + 1);
    const previousKeys = previousByFingerprint.get(fingerprint) || [];
    let clientKey = previousKeys.find((key) => !usedKeys.has(key));
    if (!clientKey) clientKey = `widget-${shortHash(fingerprint)}-${fingerprint.length}-${occurrence}`;
    usedKeys.add(clientKey);
    return { ...widget, _clientKey: clientKey };
  });

  if (!preserveCurrentOrder || !Array.isArray(current) || current.length === 0) return keyed;
  const byKey = new Map(keyed.map((widget) => [widget._clientKey, widget]));
  const ordered = [];
  for (const previous of current) {
    const updated = byKey.get(previous?._clientKey);
    if (updated) {
      ordered.push(updated);
      byKey.delete(previous._clientKey);
    }
  }
  for (const widget of keyed) {
    if (byKey.delete(widget._clientKey)) ordered.push(widget);
  }
  return ordered;
}

export function dashboardLayoutOrder(currentKeys, desiredKeys) {
  if (!Array.isArray(currentKeys) || !Array.isArray(desiredKeys) || currentKeys.length !== desiredKeys.length) return null;
  if (new Set(currentKeys).size !== currentKeys.length || new Set(desiredKeys).size !== desiredKeys.length) return null;
  const positions = new Map(currentKeys.map((key, index) => [key, index]));
  const order = desiredKeys.map((key) => positions.get(key));
  return order.some((index) => index === undefined) ? null : order;
}

export function restoreDashboardWidgetOrder(widgets, confirmedKeys) {
  if (!Array.isArray(widgets) || !Array.isArray(confirmedKeys) || widgets.length !== confirmedKeys.length) return null;
  const byKey = new Map(widgets.map((widget) => [widget?._clientKey, widget]));
  if (byKey.size !== widgets.length || new Set(confirmedKeys).size !== confirmedKeys.length) return null;
  const restored = confirmedKeys.map((key) => byKey.get(key));
  return restored.some((widget) => !widget) ? null : restored;
}

export function createDashboardLayoutPersistence({ saveLayout, loadAuthoritative }) {
  const confirmed = new Map();
  const authoritative = new Map();
  const blocked = new Set();
  const blockingErrors = new Map();

  function validKeys(keys) {
    return Array.isArray(keys) && keys.every((key) => typeof key === "string" && key)
      && new Set(keys).size === keys.length;
  }

  function seed(dashboardId, snapshot) {
    if (!dashboardId || !validKeys(snapshot?.keys)) throw new Error("Authoritative layout keys are invalid.");
    confirmed.set(dashboardId, [...snapshot.keys]);
    authoritative.set(dashboardId, snapshot);
    blocked.delete(dashboardId);
    blockingErrors.delete(dashboardId);
  }

  return {
    seed,
    invalidate(dashboardId) {
      confirmed.delete(dashboardId);
      authoritative.delete(dashboardId);
      blocked.add(dashboardId);
    },
    isBlocked(dashboardId) {
      return blocked.has(dashboardId);
    },
    confirmedKeys(dashboardId) {
      const keys = confirmed.get(dashboardId);
      return keys ? [...keys] : null;
    },
    authoritative(dashboardId) {
      return authoritative.get(dashboardId) || null;
    },
    async save(dashboardId, desiredKeys) {
      if (blocked.has(dashboardId)) return { status: "blocked", ...(blockingErrors.get(dashboardId) || {}) };
      const order = dashboardLayoutOrder(confirmed.get(dashboardId), desiredKeys);
      if (!order) return { status: "conflict", authoritative: authoritative.get(dashboardId) || null };
      try {
        await saveLayout(dashboardId, order);
        confirmed.set(dashboardId, [...desiredKeys]);
        const snapshot = authoritative.get(dashboardId);
        const widgets = restoreDashboardWidgetOrder(snapshot?.widgets, desiredKeys);
        if (snapshot && widgets) authoritative.set(dashboardId, { ...snapshot, widgets, keys: [...desiredKeys] });
        return { status: "saved", authoritative: authoritative.get(dashboardId) || null };
      } catch (error) {
        confirmed.delete(dashboardId);
        authoritative.delete(dashboardId);
        blocked.add(dashboardId);
        try {
          const snapshot = await loadAuthoritative(dashboardId);
          seed(dashboardId, snapshot);
          return { status: "recovered", error, authoritative: snapshot };
        } catch (refreshError) {
          blockingErrors.set(dashboardId, { error, refreshError });
          return { status: "unsaved", error, refreshError };
        }
      }
    },
  };
}

export function resolveDashboardWidgetDrop(widgets, dragState, targetKey, dashboardId) {
  if (!dragState || dragState.dashboardId !== dashboardId || !Array.isArray(widgets)) return null;
  const from = widgets.findIndex((widget) => widget?._clientKey === dragState.widgetKey);
  const target = widgets.findIndex((widget) => widget?._clientKey === targetKey);
  return from < 0 || target < 0 || from === target ? null : { from, target };
}

export function dashboardSourceEntries(board, connections = []) {
  const connectionIds = [...new Set(
    (Array.isArray(board?.connections) ? board.connections : []).filter(Boolean),
  )];
  const namesById = new Map(
    (Array.isArray(connections) ? connections : []).map((connection) => [connection?.id, connection?.name]),
  );
  const widgetNamesById = new Map(
    (Array.isArray(board?.widgets) ? board.widgets : [])
      .filter((widget) => widget?.connection_id && widget?.connection)
      .map((widget) => [widget.connection_id, widget.connection]),
  );
  if (connectionIds.length) {
    return connectionIds.map((id, index) => ({
      id,
      name: namesById.get(id) || widgetNamesById.get(id) || `Data source ${index + 1}`,
    }));
  }
  const fallbackNames = [...new Set(
    (Array.isArray(board?.widgets) ? board.widgets : []).map((widget) => widget?.connection).filter(Boolean),
  )];
  return fallbackNames.map((name, index) => ({ id: `widget-source-${index}`, name }));
}

export function dashboardSummary(board, refreshState = null) {
  const widgets = Array.isArray(board?.widgets) ? board.widgets : [];
  const transforms = Array.isArray(board?.transforms) ? board.transforms : [];
  const connectionIds = Array.isArray(board?.connections) ? board.connections.filter(Boolean) : [];
  const sources = [...new Set(widgets.map((widget) => widget?.connection).filter(Boolean))];
  const errorCount = widgets.filter((widget) => Boolean(widget?.error)).length;

  let status = "Waiting for dashboard data";
  let detail = "No widget queries have returned data yet.";
  let tone = "idle";
  let stale = false;
  if (errorCount) {
    status = `${errorCount} widget${errorCount === 1 ? "" : "s"} ${errorCount === 1 ? "needs" : "need"} attention`;
    detail = "Review the affected cards in the canvas.";
    tone = "warning";
  } else if (widgets.length) {
    status = "All widgets refreshed";
    detail = "Saved queries ran against the latest data.";
    tone = "healthy";
  }

  if (refreshState?.status === "refreshing") {
    status = "Refreshing dashboard";
    detail = widgets.length ? "Showing data from the last successful run." : "Running the dashboard queries.";
    tone = "idle";
    stale = widgets.length > 0;
  } else if (refreshState?.status === "failed") {
    status = "Latest refresh failed";
    detail = widgets.length ? "Showing data from the last successful run." : "Dashboard data could not be loaded.";
    tone = "warning";
    stale = true;
  }

  return {
    widgetCount: widgets.length,
    sourceCount: new Set(connectionIds).size || sources.length,
    transformCount: transforms.length,
    errorCount,
    sources,
    status,
    detail,
    tone,
    stale,
  };
}

export function reorderDashboardWidgets(widgets, from, target) {
  if (!Array.isArray(widgets) || from === target || from < 0 || target < 0 || from >= widgets.length || target >= widgets.length) {
    return null;
  }
  const order = widgets.map((_widget, index) => index);
  order.splice(target, 0, order.splice(from, 1)[0]);
  return { order, widgets: order.map((index) => widgets[index]) };
}
