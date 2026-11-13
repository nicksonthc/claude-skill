"""The times a 5-field cron expression fires, in UTC, so the scorecard can find runs that never happened.

Supports `*`, lists, ranges, steps and month or weekday names. As in cron, when both day-of-month and day-of-week
are restricted, a day matches either one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

NAMES = {
    **{
        m: i
        for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
    },
    **{d: i for i, d in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])},
}
BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def field(text: str, low: int, high: int) -> set:
    values: set = set()
    for part in text.lower().split(","):
        body, _, step = part.partition("/")
        if body == "*":
            start, end = low, high
        else:
            first, _, last = body.partition("-")
            start = int(NAMES.get(first, first))
            end = int(NAMES.get(last, last)) if last else (high if step else start)
        values.update(range(start, end + 1, int(step) if step else 1))
    return values


def parse(expression: str) -> tuple:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError(f"cron needs 5 fields: {expression!r}")
    minutes, hours, days, months, weekdays = (field(p, lo, hi) for p, (lo, hi) in zip(parts, BOUNDS))
    weekdays = {0 if d == 7 else d for d in weekdays}
    return minutes, hours, days, months, weekdays, parts[2] != "*", parts[4] != "*"


def slots(expression: str, start: datetime, end: datetime) -> list:
    """Every firing time in [start, end), oldest first."""
    minutes, hours, days, months, weekdays, day_set, weekday_set = parse(expression)
    out, day = [], start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        weekday = (day.weekday() + 1) % 7  # cron: 0 is Sunday
        by_day, by_weekday = day.day in days, weekday in weekdays
        if day_set and weekday_set:
            hit = by_day or by_weekday
        else:
            hit = by_day and by_weekday
        if day.month in months and hit:
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    when = day.replace(hour=hour, minute=minute)
                    if start <= when < end:
                        out.append(when)
        day += timedelta(days=1)
    return out
