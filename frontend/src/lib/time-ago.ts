const relativeTime = new Intl.RelativeTimeFormat('en', { numeric: 'always' })
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [['day', 86_400_000], ['hour', 3_600_000], ['minute', 60_000]]

// "2 hours ago", "3 days ago"; anything under a minute (or in the future) reads "just now".
export function timeAgo(iso: string, now = Date.now()): string {
  const elapsed = now - new Date(iso).getTime()
  const unit = UNITS.find(([, size]) => elapsed >= size)
  return unit ? relativeTime.format(-Math.floor(elapsed / unit[1]), unit[0]) : 'just now'
}
