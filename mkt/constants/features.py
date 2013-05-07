from tower import ugettext_lazy as _lazy


# WARNING: When adding a new app feature here also include a migration.
#
# WARNING: Order matters here. Don't re-order these or alphabetize them. If you
# add new ones put them on the end.
#
# These are used to dynamically generate the field list for the AppFeatures
# django model in mkt.webapps.models.
APP_FEATURES = (
    ('APPS', _lazy(u'Apps')),
    ('PACKAGED_APPS', _lazy(u'Packaged apps')),
    ('PAY', _lazy(u'Web Payment')),
    ('ACTIVITY', _lazy(u'Web Activities')),
    ('LIGHT_EVENTS', _lazy(u'Ambient Light Sensor')),
    ('ARCHIVE', _lazy(u'Archive')),
    ('BATTERY', _lazy(u'Battery Status')),
    ('BLUETOOTH', _lazy(u'Bluetooth')),
    ('CONTACTS', _lazy(u'Contacts')),
    ('DEVICE_STORAGE', _lazy(u'Device Storage')),
    ('INDEXEDDB', _lazy(u'IndexedDB')),
    ('GEOLOCATION', _lazy(u'Geolocation')),
    ('IDLE', _lazy(u'Idle')),
    ('NETWORK_INFO', _lazy(u'Network Information')),
    ('NETWORK_STATS', _lazy(u'Network Stats')),
    ('PROXIMITY', _lazy(u'Proximity')),
    ('PUSH', _lazy(u'Simple Push')),
    ('ORIENTATION', _lazy(u'Screen Orientation')),
    ('TIME_CLOCK', _lazy(u'Time/Clock')),
    ('VIBRATE', _lazy(u'Vibration')),
    ('FM', _lazy(u'WebFM')),
    ('SMS', _lazy(u'WebSMS')),
    ('TOUCH', _lazy(u'Touch')),
    ('QHD', _lazy(u'Smartphone-Sized Displays')),
    ('MP3', _lazy(u'MP3')),
    ('AUDIO', _lazy(u'Audio')),
    ('WEBAUDIO', _lazy(u'Web Audio')),
    ('VIDEO_H264', _lazy(u'H.264')),
    ('VIDEO_WEBM', _lazy(u'WebM')),
    ('FULLSCREEN', _lazy(u'Full Screen')),
    ('GAMEPAD', _lazy(u'Gamepad')),
    ('QUOTA', _lazy(u'Quota Management')),
)
