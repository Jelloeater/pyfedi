# from https://medium.com/hacking-and-gonzo/how-reddit-ranking-algorithms-work-ef111e33d0d9

from math import sqrt, log
from datetime import datetime, timedelta



epoch = datetime(1970, 1, 1)


def epoch_seconds(date):
    td = date - epoch
    return td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)


def score(ups, downs):
    return ups - downs


# used for ranking stories
def hot(ups, downs, date):
    s = score(ups, downs)
    order = log(max(abs(s), 1), 10)
    sign = 1 if s > 0 else -1 if s < 0 else 0
    seconds = epoch_seconds(date) - 1134028003      # this value seems to be an arbitrary time in 2005.
    return round(sign * order + seconds / 45000, 7)


# used for ranking comments
def _confidence(ups, downs):
    n = ups + downs

    if n == 0:
        return 0

    z = 1.281551565545
    p = float(ups) / n

    left = p + 1 / (2 * n) * z * z
    right = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    under = 1 + 1 / n * z * z

    return (left - right) / under


def confidence(ups, downs):
    if ups + downs == 0:
        return 0
    else:
        return _confidence(ups, downs)