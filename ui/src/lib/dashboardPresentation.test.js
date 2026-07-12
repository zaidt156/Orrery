import assert from "node:assert/strict";
import test from "node:test";

import {
  createSerialDashboardQueue,
  createDashboardLayoutPersistence,
  dashboardLayoutOrder,
  dashboardSourceEntries,
  dashboardSummary,
  filterDashboards,
  reconcileDashboardWidgets,
  resolveDashboardWidgetDrop,
  normalizeDashboardRefreshMs,
  reorderDashboardWidgets,
  restoreDashboardWidgetOrder,
  shouldRunScheduledDashboardRefresh,
} from "./dashboardPresentation.js";

test("filterDashboards matches saved dashboards by name or model without reordering them", () => {
  const dashboards = [
    { id: "one", name: "Revenue pulse", model: "openai/gpt-5.6" },
    { id: "two", name: "Support health", model: "anthropic/claude-sonnet-5" },
    { id: "three", name: "Sales forecast", model: "anthropic/claude-sonnet-5" },
  ];

  assert.deepEqual(filterDashboards(dashboards, "support").map((item) => item.id), ["two"]);
  assert.deepEqual(filterDashboards(dashboards, "CLAUDE").map((item) => item.id), ["two", "three"]);
  assert.equal(filterDashboards(dashboards, "missing").length, 0);
  assert.equal(filterDashboards(dashboards, "  "), dashboards);
});

test("dashboardSummary derives a truthful health overview from the current run result", () => {
  const summary = dashboardSummary({
    widgets: [
      { title: "Revenue", connection: "warehouse" },
      { title: "Orders", connection: "warehouse" },
      { title: "Returns", connection: "support", error: "query timed out" },
      { title: "Notes", connection: "" },
    ],
    transforms: [{ name: "orders_clean" }, { name: "daily_revenue" }],
    connections: ["warehouse-id", "support-id"],
  });

  assert.deepEqual(summary, {
    widgetCount: 4,
    sourceCount: 2,
    transformCount: 2,
    errorCount: 1,
    sources: ["warehouse", "support"],
    status: "1 widget needs attention",
    detail: "Review the affected cards in the canvas.",
    tone: "warning",
    stale: false,
  });
});

test("dashboardSummary handles a board that has no widgets yet", () => {
  assert.deepEqual(dashboardSummary(null), {
    widgetCount: 0,
    sourceCount: 0,
    transformCount: 0,
    errorCount: 0,
    sources: [],
    status: "Waiting for dashboard data",
    detail: "No widget queries have returned data yet.",
    tone: "idle",
    stale: false,
  });
});

test("dashboardSummary counts authoritative connection ids even when some have no widgets", () => {
  const summary = dashboardSummary({
    widgets: [
      { connection: "warehouse" },
      { connection: "warehouse" },
      { connection: "support" },
    ],
    connections: ["one", "two", "three"],
  });

  assert.equal(summary.sourceCount, 3);
  assert.deepEqual(summary.sources, ["warehouse", "support"]);
  assert.equal(summary.detail, "Saved queries ran against the latest data.");
});

test("dashboardSourceEntries preserves distinct connection ids with duplicate display names", () => {
  const entries = dashboardSourceEntries(
    { connections: ["warehouse-a", "warehouse-b", "unused"] },
    [
      { id: "warehouse-a", name: "Warehouse" },
      { id: "warehouse-b", name: "Warehouse" },
      { id: "unused", name: "Archive" },
    ],
  );

  assert.deepEqual(entries, [
    { id: "warehouse-a", name: "Warehouse" },
    { id: "warehouse-b", name: "Warehouse" },
    { id: "unused", name: "Archive" },
  ]);
});

test("dashboardSummary marks previous data stale when the latest refresh failed", () => {
  const summary = dashboardSummary(
    { widgets: [{ title: "Revenue", connection: "warehouse" }], connections: ["warehouse-id"] },
    { status: "failed" },
  );

  assert.equal(summary.status, "Latest refresh failed");
  assert.equal(summary.detail, "Showing data from the last successful run.");
  assert.equal(summary.tone, "warning");
  assert.equal(summary.stale, true);
});

test("reorderDashboardWidgets returns the persisted order and leaves invalid moves alone", () => {
  const widgets = [{ title: "Revenue" }, { title: "Orders" }, { title: "Returns" }];

  assert.deepEqual(reorderDashboardWidgets(widgets, 2, 0), {
    order: [2, 0, 1],
    widgets: [widgets[2], widgets[0], widgets[1]],
  });
  assert.equal(reorderDashboardWidgets(widgets, 1, 1), null);
  assert.equal(reorderDashboardWidgets(widgets, -1, 2), null);
  assert.equal(reorderDashboardWidgets(widgets, 0, 3), null);
});

test("normalizeDashboardRefreshMs only accepts the supported refresh schedules", () => {
  assert.equal(normalizeDashboardRefreshMs(0), 0);
  assert.equal(normalizeDashboardRefreshMs("30000"), 30000);
  assert.equal(normalizeDashboardRefreshMs(60000), 60000);
  assert.equal(normalizeDashboardRefreshMs("300000"), 300000);
  assert.equal(normalizeDashboardRefreshMs("1000"), 0);
  assert.equal(normalizeDashboardRefreshMs("not-a-number"), 0);
  assert.equal(normalizeDashboardRefreshMs(null), 0);
});

test("scheduled refresh only runs for a visible dashboard with an idle request queue", () => {
  assert.equal(shouldRunScheduledDashboardRefresh("visible", false), true);
  assert.equal(shouldRunScheduledDashboardRefresh("hidden", false), false);
  assert.equal(shouldRunScheduledDashboardRefresh("visible", true), false);
});

test("serial dashboard queue never overlaps tasks and continues after rejection", async () => {
  const queue = createSerialDashboardQueue();
  const events = [];
  let releaseFirst;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });

  const first = queue.enqueue(async () => {
    events.push("first:start");
    await firstGate;
    events.push("first:end");
    throw new Error("expected failure");
  });
  const second = queue.enqueue(async () => {
    events.push("second:start");
    events.push("second:end");
    return "done";
  });

  await Promise.resolve();
  assert.deepEqual(events, ["first:start"]);
  assert.equal(queue.isBusy(), true);
  releaseFirst();
  await assert.rejects(first, /expected failure/);
  assert.equal(await second, "done");
  await queue.whenIdle();
  assert.deepEqual(events, ["first:start", "first:end", "second:start", "second:end"]);
  assert.equal(queue.isBusy(), false);
});

test("reconcileDashboardWidgets keeps stable keys and the current layout while updating data", () => {
  const initial = reconcileDashboardWidgets([
    { title: "Revenue", type: "stat", sql: "select 1", rows: [[1]] },
    { title: "Orders", type: "bar", sql: "select 2", rows: [[2]] },
    { title: "Returns", type: "table", sql: "select 3", rows: [[3]] },
  ]);
  const reordered = [initial[2], initial[0], initial[1]];
  const incoming = [
    { title: "Revenue", type: "stat", sql: "select 1", rows: [[10]] },
    { title: "Orders", type: "bar", sql: "select 2", rows: [[20]] },
    { title: "Returns", type: "table", sql: "select 3", rows: [[30]] },
  ];
  const refreshed = reconcileDashboardWidgets(incoming, reordered);
  const serverOrder = reconcileDashboardWidgets(incoming, reordered, false);

  assert.deepEqual(refreshed.map((widget) => widget.title), ["Returns", "Revenue", "Orders"]);
  assert.deepEqual(refreshed.map((widget) => widget._clientKey), reordered.map((widget) => widget._clientKey));
  assert.deepEqual(refreshed.map((widget) => widget.rows[0][0]), [30, 10, 20]);
  assert.deepEqual(serverOrder.map((widget) => widget.title), ["Revenue", "Orders", "Returns"]);
});

test("dashboardLayoutOrder computes a server-relative permutation and rejects stale identities", () => {
  assert.deepEqual(dashboardLayoutOrder(["a", "b", "c"], ["c", "a", "b"]), [2, 0, 1]);
  assert.deepEqual(dashboardLayoutOrder(["c", "a", "b"], ["b", "c", "a"]), [2, 0, 1]);
  assert.equal(dashboardLayoutOrder(["a", "b"], ["a", "missing"]), null);
  assert.equal(dashboardLayoutOrder(["a", "a"], ["a", "a"]), null);
});

test("restoreDashboardWidgetOrder rolls an optimistic layout back to confirmed keys", () => {
  const widgets = [
    { _clientKey: "c", title: "Returns" },
    { _clientKey: "a", title: "Revenue" },
    { _clientKey: "b", title: "Orders" },
  ];

  assert.deepEqual(
    restoreDashboardWidgetOrder(widgets, ["a", "b", "c"]).map((widget) => widget._clientKey),
    ["a", "b", "c"],
  );
  assert.equal(restoreDashboardWidgetOrder(widgets, ["a", "missing", "c"]), null);
});

test("layout persistence recovers a committed-but-lost response before rebasing a queued move", async () => {
  let serverKeys = ["a", "b", "c"];
  let loseFirstResponse = true;
  const sentOrders = [];
  const persistence = createDashboardLayoutPersistence({
    saveLayout: async (_dashboardId, order) => {
      sentOrders.push(order);
      serverKeys = order.map((index) => serverKeys[index]);
      if (loseFirstResponse) {
        loseFirstResponse = false;
        throw new Error("response lost after commit");
      }
    },
    loadAuthoritative: async () => ({ widgets: serverKeys.map((_key) => ({})), keys: [...serverKeys] }),
  });
  persistence.seed("board", { widgets: [], keys: ["a", "b", "c"] });
  const queue = createSerialDashboardQueue();

  const first = queue.enqueue(() => persistence.save("board", ["c", "a", "b"]));
  const second = queue.enqueue(() => persistence.save("board", ["b", "c", "a"]));

  assert.equal((await first).status, "recovered");
  assert.equal((await second).status, "saved");
  assert.deepEqual(sentOrders, [[2, 0, 1], [2, 0, 1]]);
  assert.deepEqual(serverKeys, ["b", "c", "a"]);
  assert.deepEqual(persistence.confirmedKeys("board"), ["b", "c", "a"]);
});

test("layout persistence blocks later saves until an authoritative refresh succeeds", async () => {
  let saveCalls = 0;
  const persistence = createDashboardLayoutPersistence({
    saveLayout: async () => { saveCalls += 1; throw new Error("unknown commit state"); },
    loadAuthoritative: async () => { throw new Error("refresh unavailable"); },
  });
  persistence.seed("board", { widgets: [], keys: ["a", "b"] });

  assert.equal((await persistence.save("board", ["b", "a"])).status, "unsaved");
  assert.equal((await persistence.save("board", ["a", "b"])).status, "blocked");
  assert.equal(saveCalls, 1);

  persistence.seed("board", { widgets: [], keys: ["b", "a"] });
  assert.equal(persistence.isBlocked("board"), false);
});

test("resolveDashboardWidgetDrop ignores external and stale drag gestures", () => {
  const widgets = [{ _clientKey: "a" }, { _clientKey: "b" }, { _clientKey: "c" }];
  const drag = { dashboardId: "board-1", widgetKey: "c" };

  assert.deepEqual(resolveDashboardWidgetDrop(widgets, drag, "a", "board-1"), { from: 2, target: 0 });
  assert.equal(resolveDashboardWidgetDrop(widgets, null, "a", "board-1"), null);
  assert.equal(resolveDashboardWidgetDrop(widgets, drag, "a", "board-2"), null);
  assert.equal(resolveDashboardWidgetDrop(widgets, { dashboardId: "board-1", widgetKey: "gone" }, "a", "board-1"), null);
  assert.equal(resolveDashboardWidgetDrop(widgets, drag, "gone", "board-1"), null);
});
