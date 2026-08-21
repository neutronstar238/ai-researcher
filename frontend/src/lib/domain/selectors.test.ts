import { runFixture, stageFixtures } from "../../test/fixtures";
import { coveragePercent, selectCurrentRun } from "./selectors";

test("selects the newest active run before a newer completed run", () => {
  const runs = [
    runFixture({ run_id: "completed", status: "completed", created_at: "2026-08-20T09:00:00Z", finished_at: "2026-08-20T10:00:00Z" }),
    runFixture({ run_id: "older-running", status: "running", created_at: "2026-08-20T06:00:00Z", finished_at: null }),
    runFixture({ run_id: "newer-queued", status: "queued", created_at: "2026-08-20T08:00:00Z", finished_at: null }),
  ];

  expect(selectCurrentRun(runs)?.run_id).toBe("newer-queued");
  expect(runs.map((run) => run.run_id)).toEqual(["completed", "older-running", "newer-queued"]);
});

test("uses the newest finished-or-created timestamp when no run is active", () => {
  const runs = [
    runFixture({ run_id: "newer-created", status: "failed", created_at: "2026-08-20T09:00:00Z", finished_at: null }),
    runFixture({ run_id: "newer-finished", status: "completed", created_at: "2026-08-20T06:00:00Z", finished_at: "2026-08-20T10:00:00Z" }),
  ];

  expect(selectCurrentRun(runs)?.run_id).toBe("newer-finished");
  expect(runs.map((run) => run.run_id)).toEqual(["newer-created", "newer-finished"]);
});

test("returns null when there are no runs", () => {
  expect(selectCurrentRun([])).toBeNull();
});

test("returns null coverage when no stage data exists", () => {
  expect(coveragePercent([])).toBeNull();
});

test("rounds completed stage coverage to a whole percentage", () => {
  expect(coveragePercent(stageFixtures(1).slice(0, 3))).toBe(33);
});

test.each([
  [
    "active runs with invalid timestamps",
    [
      runFixture({ run_id: "active-z", status: "running", created_at: "not-a-date", finished_at: null }),
      runFixture({ run_id: "active-a", status: "queued", created_at: "not-a-date", finished_at: null }),
    ],
    "active-a",
  ],
  [
    "inactive runs with invalid timestamps",
    [
      runFixture({ run_id: "inactive-z", status: "failed", created_at: "not-a-date", finished_at: null }),
      runFixture({ run_id: "inactive-a", status: "completed", created_at: "not-a-date", finished_at: null }),
    ],
    "inactive-a",
  ],
  [
    "active runs with identical timestamps",
    [
      runFixture({ run_id: "active-z", status: "running", created_at: "2026-08-20T08:00:00Z", finished_at: null }),
      runFixture({ run_id: "active-a", status: "cancel_requested", created_at: "2026-08-20T08:00:00Z", finished_at: null }),
    ],
    "active-a",
  ],
  [
    "inactive runs with identical timestamps",
    [
      runFixture({ run_id: "inactive-z", status: "failed", created_at: "2026-08-20T08:00:00Z", finished_at: null }),
      runFixture({ run_id: "inactive-a", status: "completed", created_at: "2026-08-20T08:00:00Z", finished_at: null }),
    ],
    "inactive-a",
  ],
])("uses run_id to deterministically break ties for %s without mutating input", (_caseName, runs, expectedRunId) => {
  const originalOrder = runs.map((run) => run.run_id);

  expect(selectCurrentRun(runs)?.run_id).toBe(expectedRunId);
  expect(runs.map((run) => run.run_id)).toEqual(originalOrder);
});
