import re

from versions.compare import version_int as vint


# These are the minimum versions required for `navigator.mozApps` support.
APP_PLATFORMS = [
    # Firefox for Desktop.
    (
        [
            re.compile('Firefox/([\d.]+)')
        ],
        vint('16.0')
    ),
    # Firefox for Android.
    (
        [
            re.compile('Fennec/([\d.]+)'),
            re.compile('Android; Mobile; rv:([\d.]+)'),
            re.compile('Mobile; rv:([\d.]+)')
        ],
        vint('17.0')
    )
]
