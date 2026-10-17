/** EXTENSION POINT: the site's wall clock, matching the backend's SITE_TZ. */
export const SITE_TIME_ZONE = "Asia/Singapore"

/** "17 Oct, 14:05" in site time. The API sends naive UTC with no offset, and
 *  `new Date("2026-10-17T06:05:00")` would read that as browser-local time —
 *  so append the Z when the string carries no zone. */
export function fmtTime(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z")
  return d.toLocaleString("en-GB", {
    timeZone: SITE_TIME_ZONE,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}
