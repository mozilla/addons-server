from ordereddict import OrderedDict

from django.conf import settings

from tower import ugettext_lazy as _lazy


# WARNING: When adding a new app feature here also include a migration.
#
# WARNING: Order matters here. Don't re-order these or alphabetize them. If you
# add new ones put them on the end.
#
# These are used to dynamically generate the field list for the AppFeatures
# django model in mkt.webapps.models.
APP_FEATURES = OrderedDict([
    ('APPS', {
        'name': _lazy(u'Apps'),
        'description': _lazy(u'The app requires the `navigator.mozApps` API.'),
        'apis': ('navigator.mozApps',),
    }),
    ('PACKAGED_APPS', {
        'name': _lazy(u'Packaged apps'),
        'description': _lazy(u''),
        'apis': ('navigator.mozApps.installPackage',),
    }),
    ('PAY', {
        'name': _lazy(u'Web Payment'),
        'description': _lazy(u'The app requires the `navigator.mozApps` API.'),
        'apis': ('navigator.pay', 'navigator.mozPay',),
    }),
    ('ACTIVITY', {
        'name': _lazy(u'Web Activities'),
        'description': _lazy(u'The app requires Web Activities '
                              '(the `MozActivity` API).'),
        'apis': ('MozActivity',),
    }),
    ('LIGHT_EVENTS', {
        'name': _lazy(u'Ambient Light Sensor'),
        'description': _lazy(u'The app requires an ambient light sensor '
                              '(the `ondevicelight` API).'),
        'apis': ('window.ondevicelight',),
    }),
    ('ARCHIVE', {
        'name': _lazy(u'Archive'),
        'description': u'',
        'apis': (),
    }),
    ('BATTERY', {
        'name': _lazy(u'Battery'),
        'description': _lazy(u'The app requires the `navigator.battery` API.'),
        'apis': ('navigator.battery',),
    }),
    ('BLUETOOTH', {
        'name': u'Bluetooth',
        'description': _lazy(u'The app requires the `navigator.mozBluetooth` '
                              'API.'),
        'apis': ('navigator.bluetooth', 'navigator.mozBluetooth'),
    }),
    ('CONTACTS', {
        'name': _lazy(u'Contacts'),
        'description': _lazy(u'The app requires the `navigator.mozContacts` '
                              'API.'),
        'apis': ('navigator.contacts', 'navigator.mozContacts'),
    }),
    ('DEVICE_STORAGE', {
        'name': _lazy(u'Device Storage'),
        'description': _lazy(u'The app requires the Device Storage API to '
                              'access files on the filesystem.'),
        'apis': ('navigator.getDeviceStorage',),
    }),
    ('INDEXEDDB', {
        'name': u'IndexedDB',
        'description': _lazy(u'The app requires the platform to support '
                              'IndexedDB.'),
        'apis': ('navigator.indexedDB', 'navigator.mozIndexedDB'),
    }),
    ('GEOLOCATION', {
        'name': _lazy(u'Geolocation'),
        'description': _lazy(u'The app requires the platform to support the '
                              '`navigator.geolocation` API.'),
        'apis': ('navigator.geolocation',),
    }),
    ('IDLE', {
        'name': _lazy(u'Idle'),
        'description': u'',
        'apis': ('addIdleObserver', 'removeIdleObserver'),
    }),
    ('NETWORK_INFO', {
        'name': _lazy(u'Network Information'),
        'description': _lazy(u'The app requires the ability to get '
                              'information about the network connection (the '
                              '`navigator.mozConnection` API).'),
        'apis': ('navigator.mozConnection', 'navigator.mozMobileConnection'),
    }),
    ('NETWORK_STATS', {
        'name': _lazy(u'Network Stats'),
        'description': _lazy(u'The app requires the '
                              '`navigator.mozNetworkStats` API.'),
        'apis': ('navigator.networkStats', 'navigator.mozNetworkStats'),
    }),
    ('PROXIMITY', {
        'name': _lazy(u'Proximity'),
        'description': _lazy(u'The app requires a proximity sensor (the '
                              '`ondeviceproximity` API).'),
        'apis': ('navigator.ondeviceproximity',),
    }),
    ('PUSH', {
        'name': _lazy(u'Simple Push'),
        'description': _lazy(u'The app requires the `navigator.mozPush` API.'),
        'apis': ('navigator.push', 'navigator.mozPush'),
    }),
    ('ORIENTATION', {
        'name': _lazy(u'Screen Orientation'),
        'description': _lazy(u'The app requires the platform to support the '
                              '`ondeviceorientation` API.'),
        'apis': ('ondeviceorientation',),
    }),
    ('TIME_CLOCK', {
        'name': _lazy(u'Time/Clock'),
        'description': _lazy(u'The app requires the `navigator.mozTime` API.'),
        'apis': ('navigator.time', 'navigator.mozTime'),
    }),
    ('VIBRATE', {
        'name': _lazy(u'Vibration'),
        'description': _lazy(u'The app requires the device to support '
                              'vibration (the `navigator.vibrate` API).'),
        'apis': ('navigator.vibrate',),
    }),
    ('FM', {
        'name': u'WebFM',
        'description': _lazy(u'The app requires the `navigator.mozFM` or '
                              '`navigator.mozFMRadio` APIs.'),
        'apis': ('navigator.mozFM', 'navigator.mozFMRadio'),
    }),
    ('SMS', {
        'name': u'WebSMS',
        'description': _lazy(u'The app requires the `navigator.mozSms` API.'),
        'apis': ('navigator.mozSms', 'navigator.mozSMS'),
    }),
    ('TOUCH', {
        'name': _lazy(u'Touch'),
        'description': _lazy(u'The app requires the platform to support touch '
                               'events. This option indicates that the app '
                               'will not function when used with a mouse.'),
        'apis': ('window.ontouchstart',),
    }),
    ('QHD', {
        'name': _lazy(u'Smartphone-Sized Displays'),
        'description': _lazy(u'The app requires the platform to have a '
                              'smartphone-sized display (having qHD '
                              'resolution). This option indicates that the '
                              'app will be unusable on larger displays '
                              '(e.g., tablets, desktop).'),
        'apis': (),
    }),
    ('MP3', {
        'name': u'MP3',
        'description': _lazy(u'The app requires that the platform can decode '
                              'and play MP3 files.'),
        'apis': (),
    }),
    ('AUDIO', {
        'name': _lazy(u'Audio'),
        'description': _lazy(u'The app requires that the platform supports '
                              'the HTML5 audio API.'),
        'apis': ('Audio',),
    }),
    ('WEBAUDIO', {
        'name': _lazy(u'Web Audio'),
        'description': _lazy(u'The app requires that the platform supports '
                              'the Web Audio API (`window.AudioContext`).'),
        'apis': ('AudioContext', 'mozAudioContext', 'webkitAudioContext'),
    }),
    ('VIDEO_H264', {
        'name': u'H.264',
        'description': _lazy(u'The app requires that the platform can decode '
                              'and play H.264 video files.'),
        'apis': (),
    }),
    ('VIDEO_WEBM', {
        'name': u'WebM',
        'description': _lazy(u'The app requires that the platform can decode '
                              'and play WebM video files (VP8).'),
        'apis': (),
    }),
    ('FULLSCREEN', {
        'name': _lazy(u'Full Screen'),
        'description': _lazy(u'The app requires the Full Screen API '
                              '(`requestFullScreen` or '
                              '`mozRequestFullScreen`).'),
        'apis': ('document.documentElement.requestFullScreen',),
    }),
    ('GAMEPAD', {
        'name': _lazy(u'Gamepad'),
        'description': _lazy(u'The app requires the platform to support the '
                              'gamepad API (`navigator.getGamepads`).'),
        'apis': ('navigator.getGamepad', 'navigator.mozGetGamepad'),
    }),
    ('QUOTA', {
        'name': _lazy(u'Quota Management'),
        'description': _lazy(u'The app requires the platform to allow '
                              'persistent storage limit increases above the '
                              'normally allowed limits for an app '
                              '(`window.StorageInfo` or '
                              '`window.persistentStorage`).'),
        'apis': ('navigator.persistentStorage', 'navigator.temporaryStorage'),
    }),
])


class FeatureProfile(OrderedDict):
    """
    Convenience class for performing conversion operations on feature profile
    representations.
    """

    def __init__(self, **kwargs):
        """
        Creates a FeatureProfile object.

        Takes kwargs to the features to enable or disable. Features not
        specified but that are in APP_FEATURES will be False by default.

        E.g.:

            >>> FeatureProfile(sms=True).to_signature()
            '400.32.1'

        """
        super(FeatureProfile, self).__init__()
        for af in APP_FEATURES:
            key = af.lower()
            self[key] = kwargs.get(key, False)

    @classmethod
    def from_binary(cls, binary):
        """
        Construct a FeatureProfile object from a binary string.

        >>> FeatureProfile.from_binary('01000010...')
        FeatureProfile([('apps', False), ('packaged_apps', True), ...)

        """
        instance = cls()
        if not binary:
            binary = '0' * len(APP_FEATURES)
        n = len(APP_FEATURES) - 1
        for i, k in enumerate(APP_FEATURES):
            instance[k.lower()] = bool(int(binary, 2) & 2 ** (n - i))
        return instance

    @classmethod
    def from_signature(cls, signature):
        """
        Construct a FeatureProfile object from a decimal signature.

        >>> FeatureProfile.from_signature('40000000.32.1')
        FeatureProfile([('apps', False), ('packaged_apps', True), ...)
        """
        dehexed = int(signature.split('.')[0], 16)
        return cls.from_binary(bin(dehexed).lstrip('0b'))

    def to_binary(self):
        """
        Convert a FeatureProfile object to its binary representation.

        >>> profile.to_binary()
        '0100000000000000000000000000000'
        """
        return ''.join('1' if v else '0' for v in self.values())

    def to_signature(self):
        """
        Convert a FeatureProfile object to its decimal signature.

        >>> profile.to_signature()
        '40000000.32.1'
        """
        profile = self.to_binary()
        return '%x.%s.%s' % (int(profile, 2), len(profile),
                             settings.APP_FEATURES_VERSION)

    def to_list(self):
        """
        Returns a list representing the true values of this profile.
        """
        return [k for k, v in self.iteritems() if v]

    def to_kwargs(self, prefix=''):
        """
        Returns a dict representing the false values of this profile.

        Parameters:
        - `prefix` - a string prepended to the key name. Helpful if being used
                     to traverse relations

        This only includes keys for which the profile is False, which is useful
        for querying apps where we want to filter by apps which do not require
        a feature.

        >>> profile = FeatureProject.from_signature(request.get('pro'))
        >>> Webapp.objects.filter(**profile.to_kwargs())

        """
        return dict((prefix + k, False) for k, v in self.iteritems() if not v)
