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
