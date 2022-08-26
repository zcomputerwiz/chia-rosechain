# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\misc.py


def format_bytes(bytes: int) -> str:
    if not isinstance(bytes, int) or bytes < 0:
        return 'Invalid'
    LABELS = ('MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB')
    BASE = 1024
    value = bytes / BASE
    for label in LABELS:
        value /= BASE
        if value < BASE:
            return f"{value:.3f} {label}"

    return f"{value:.3f} {LABELS[-1]}"


def format_minutes(minutes: int) -> str:
    if not isinstance(minutes, int):
        return 'Invalid'
    if minutes == 0:
        return 'Now'
    hour_minutes = 60
    day_minutes = 24 * hour_minutes
    week_minutes = 7 * day_minutes
    months_minutes = 43800
    year_minutes = 12 * months_minutes
    years = int(minutes / year_minutes)
    months = int(minutes / months_minutes)
    weeks = int(minutes / week_minutes)
    days = int(minutes / day_minutes)
    hours = int(minutes / hour_minutes)

    def format_unit_string(str_unit: str, count: int) -> str:
        return f"{count} {str_unit}{'s' if count > 1 else ''}"

    def format_unit(unit, count, unit_minutes, next_unit, next_unit_minutes):
        formatted = format_unit_string(unit, count)
        minutes_left = minutes % unit_minutes
        if minutes_left >= next_unit_minutes:
            formatted += ' and ' + format_unit_string(next_unit, int(minutes_left / next_unit_minutes))
        return formatted

    if years > 0:
        return format_unit('year', years, year_minutes, 'month', months_minutes)
    if months > 0:
        return format_unit('month', months, months_minutes, 'week', week_minutes)
    if weeks > 0:
        return format_unit('week', weeks, week_minutes, 'day', day_minutes)
    if days > 0:
        return format_unit('day', days, day_minutes, 'hour', hour_minutes)
    if hours > 0:
        return format_unit('hour', hours, hour_minutes, 'minute', 1)
    if minutes > 0:
        return format_unit_string('minute', minutes)
    return 'Unknown'