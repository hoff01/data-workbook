export type WeeklyCallArchiveFreshness = "current" | "lagging";

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function weeklyCallArchiveFreshness(
  product: string,
  archiveWeek: string,
  sourceWeek: string,
): WeeklyCallArchiveFreshness {
  if (!isIsoDate(archiveWeek)) {
    throw new Error(`${product} weekly call archive has an invalid week: ${archiveWeek}`);
  }
  if (!isIsoDate(sourceWeek)) {
    throw new Error(`${product} weekly source has an invalid latest week: ${sourceWeek}`);
  }
  if (archiveWeek > sourceWeek) {
    throw new Error(
      `${product} weekly call archive is newer than the weekly source: archive=${archiveWeek} source=${sourceWeek}`,
    );
  }
  return archiveWeek === sourceWeek ? "current" : "lagging";
}
