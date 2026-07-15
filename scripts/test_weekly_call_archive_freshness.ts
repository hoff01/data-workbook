import assert from "node:assert/strict";
import { weeklyCallArchiveFreshness } from "../src/weekly_call_archive_freshness.js";

assert.equal(weeklyCallArchiveFreshness("diesel", "2026-07-10", "2026-07-10"), "current");
assert.equal(
  weeklyCallArchiveFreshness("diesel", "2026-07-03", "2026-07-10"),
  "lagging",
  "an on-demand weekly call archive may lag the source without blocking dashboard rebuilds",
);
assert.throws(
  () => weeklyCallArchiveFreshness("diesel", "2026-07-17", "2026-07-10"),
  /archive is newer than the weekly source/,
);
assert.throws(() => weeklyCallArchiveFreshness("diesel", "2026-02-30", "2026-07-10"), /invalid week/);
assert.throws(() => weeklyCallArchiveFreshness("diesel", "2026-07-03", "not-a-date"), /invalid latest week/);

console.log("weekly call archive freshness contract ok");
