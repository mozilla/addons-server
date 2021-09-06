from datetime import datetime

from olympia.blocklist.utils import datetime_to_ts


def test_datetime_to_ts():
    now = datetime.now()
    assert datetime_to_ts(now) == int(now.timestamp() * 1000)
