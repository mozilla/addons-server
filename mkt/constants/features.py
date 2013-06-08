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

FEATURES_DICT = dict(APP_FEATURES)

APP_FEATURES_DESCRIPTIONS = {
    'APPS': _lazy('The app requires the `navigator.mozApps` API.'),
    'PACKAGED_APPS': _lazy(
        'The app requires the `navigator.mozApps.installPackage` API.'),
    'PAY': _lazy('The app requires the `navigator.mozPay` API.'),
    'ACTIVITY': _lazy(
        'The app requires Web Activities (the `MozActivity` API).'),
    'LIGHT_EVENTS': _lazy(
        'The app requires an ambient light sensor (the `ondevicelight` API).'),
    #'ARCHIVE': _lazy('The app requires the web archive API.'),
    'BATTERY': _lazy('The app requires the `navigator.battery` API.'),
    'BLUETOOTH': _lazy('The app requires the `navigator.mozBluetooth` API.'),
    'CONTACTS': _lazy('The app requires the `navigator.mozContacts` API.'),
    'DEVICE_STORAGE': _lazy(
        'The app requires the Device Storage API to access files on the '
        'filesyste.'),
    'INDEXEDDB': _lazy('The app requires the platform to support IndexedDB.'),
    'GEOLOCATION': _lazy(
        'The app requires the platform to support the '
        '`navigator.geolocation` API.'),
    #'IDLE': _lazy('The app requires the `addIdleObserver` API.'),
    'NETWORK_INFO': _lazy(
        'The app requires the ability to get information about the network '
        'connection (the `navigator.mozConnection` API).'),
    'NETWORK_STATS': _lazy(
        'The app requires the `navigator.mozNetworkStats` API.'),
    'PROXIMITY': _lazy(
        'The app requires a proximity sensor (the `ondeviceproximity` API).'),
    'PUSH': _lazy('The app requires the `navigator.mozPush` API.'),
    'ORIENTATION': _lazy(
        'The app requires the platform to support the `ondeviceorientation` '
        'API.'),
    'TIME_CLOCK': _lazy('The app requires the `navigator.mozTime` API.'),
    'VIBRATE': _lazy(
        'The app requires the device to support vibration (the '
        '`navigator.vibrate` API).'),
    'FM': _lazy(
        'The app requires the `navigator.mozFM` or `navigator.mozFMRadio` '
        'APIs.'),
    'SMS': _lazy('The app requires the `navigator.mozSms` API.'),
    'TOUCH': _lazy(
        'The app requires the platform to support touch events. This option '
        'indicates that the app will not function when used with a mouse.'),
    'QHD': _lazy(
        'The app requies the platform to have a smartphone-sized display '
        '(having qHD resolution). This option indicates that the app will '
        'be unusable on larger displays (e.g.: tablets, desktop, etc.).'),
    'MP3': _lazy(
        'The app requires that the platform can decode and play Mp3 files.'),
    'AUDIO': _lazy(
        'The app requires that the platform supports the HTML5 audio API.'),
    'WEBAUDIO': _lazy(
        'The app requires that the platform supports the Web Audio API '
        '(`window.AudioContext`).'),
    'VIDEO_H264': _lazy(
        'The app requires that the platform can decode and play H.264 video '
        'files.'),
    'VIDEO_WEBM': _lazy(
        'The app requires that the platform can decode and play WebM video '
        'files (VP8).'),
    'FULLSCREEN': _lazy(
        'The app requires the Full Screen API (`requestFullScreen` or '
        '`mozRequestFullScreen`).'),
    'GAMEPAD': _lazy(
        'The app requires the platform to support the gamepad API '
        '(`navigator.getGamepads`)'),
    'QUOTA': _lazy(
        'The app requires the platform to allow persistent storage limit '
        'increases above the normally allowed limits for an app '
        '(`window.StorageInfo` or `window.persistentStorage`).'),
}


class FeatureProfile(OrderedDict):
    """
    Convenience class for performing conversion operations on feature profile
    representations.
    """

    @classmethod
    def from_binary(cls, binary):
        """
        Construct a FeatureProfile object from a binary string.

        >>> FeatureProfile.from_binary('01000010...')
        FeatureProfile([('apps', False), ('packaged_apps', True), ...)

        """
        instance = cls()
        n = len(APP_FEATURES) - 1
        for i, k in enumerate(APP_FEATURES):
            instance[k[0].lower()] = bool(int(binary, 2) & 2 ** (n - i))
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
        return ''.join(['1' if v else '0' for v in self.values()])

    def to_signature(self):
        """
        Convert a FeatureProfile object to its decimal signature.

        >>> profile.to_signature()
        '40000000.32.1'
        """
        profile = self.to_binary()
        return '%x.%s.%s' % (int(profile, 2), len(profile),
                             settings.APP_FEATURES_VERSION)

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
