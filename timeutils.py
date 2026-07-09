# ============================================
# Единая точка локального времени (TIMEZONE из config)
# ============================================

import datetime
from zoneinfo import ZoneInfo

from config import TIMEZONE

_tz = ZoneInfo(TIMEZONE)


def now_local():
    return datetime.datetime.now(_tz)


def today_local():
    return now_local().date()


# Сейчас внутри окна бодрствования? Отбой за полуночью (00:00 ≤ подъёма)
# трактуется как «после подъёма ИЛИ до отбоя»
def in_wake_window(wake_time, sleep_time):
    now = now_local()
    now_minutes = now.hour * 60 + now.minute
    wake = _to_minutes(wake_time)
    sleep = _to_minutes(sleep_time)
    if wake < sleep:
        return wake <= now_minutes < sleep
    return now_minutes >= wake or now_minutes < sleep


def _to_minutes(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)
