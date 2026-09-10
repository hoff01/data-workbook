import { readFile } from "node:fs/promises";

// Compatibility entrypoint for verify:weekly: validate local exports without an EIA website request.
const PRODUCT_FILES = ["eia_weekly/diesel.csv", "eia_weekly/jet.csv", "eia_weekly/gasoline.csv"];

async function csvWeekDates(path: string): Promise<string[]> {
  const text = await readFile(path, "utf8");
  const dates = text
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split(",", 1)[0]?.trim() ?? "")
    .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    .sort();
  const uniqueDates = [...new Set(dates)];
  if (!uniqueDates.length) throw new Error(`${path} contains no week_ending rows`);
  return uniqueDates;
}

function weeklyContinuityBreaks(dates: string[]): Array<{ previous: string; current: string; deltaDays: number }> {
  const breaks: Array<{ previous: string; current: string; deltaDays: number }> = [];
  for (let index = 1; index < dates.length; index += 1) {
    const previous = dates[index - 1];
    const current = dates[index];
    const deltaDays = Math.round((Date.parse(`${current}T00:00:00Z`) - Date.parse(`${previous}T00:00:00Z`)) / 86_400_000);
    if (deltaDays !== 7) breaks.push({ previous, current, deltaDays });
  }
  return breaks;
}

const local = await Promise.all(PRODUCT_FILES.map(async (path) => {
  const dates = await csvWeekDates(path);
  return { path, latest: dates.at(-1) ?? "", continuityBreaks: weeklyContinuityBreaks(dates) };
}));
const discontinuous = local.filter((item) => item.continuityBreaks.length);
if (discontinuous.length) {
  throw new Error(
    `weekly continuity failed: ${discontinuous
      .map((item) => `${item.path}:${item.continuityBreaks
        .slice(0, 5)
        .map((gap) => `${gap.previous}->${gap.current}(${gap.deltaDays}d)`)
        .join("|")}`)
      .join(", ")}`,
  );
}
console.log(
  `weekly local continuity ok ${local
    .map((item) => `${item.path}=${item.latest}`)
    .join(" ")}`,
);
