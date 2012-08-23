import random
import urlparse

from django.conf import settings
from django.db import connection, models
from django.core.files.storage import default_storage as storage

from tower import ugettext_lazy as _lazy

import amo
from amo.models import BlobField
from lib.crypto import generate_key
from lib.cef_loggers import inapp_cef


class TooManyKeyGenAttempts(Exception):
    """Too many attempts to generate a unique key."""


class InappConfig(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', unique=False)
    chargeback_url = models.CharField(
        max_length=200, verbose_name=_lazy(u'Chargeback URL'),
        help_text=_lazy(u'Relative URL in your app that the marketplace posts '
                        u'a chargeback to. For example: /payments/chargeback'))
    postback_url = models.CharField(
        max_length=200, verbose_name=_lazy(u'Postback URL'),
        help_text=_lazy(u'Relative URL in your app that the marketplace will '
                        u'post a confirmed transaction to. For example: '
                        u'/payments/postback'))
    key_timestamp = models.CharField(max_length=10, blank=True, null=True,
                                     db_index=True,
                                     help_text='Timestamp of the disk key '
                                               'used to encrypt the private '
                                               'key in the db.')
    _encrypted_private_key = BlobField(blank=True, null=True,
                                       db_column='private_key')
    public_key = models.CharField(max_length=255, unique=True, db_index=True)
    # Allow https to be configurable only if it's declared in settings.
    # This is intended for development.
    is_https = models.BooleanField(
            default=True,
            help_text=_lazy(u'Use SSL when posting to app'))
    status = models.PositiveIntegerField(choices=amo.INAPP_STATUS_CHOICES,
                                         default=amo.INAPP_STATUS_INACTIVE,
                                         db_index=True)

    class Meta:
        db_table = 'addon_inapp'

    def is_active(self):
        return self.status == amo.INAPP_STATUS_ACTIVE

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.status)

    def get_private_key(self):
        """Get the real private key from the database."""
        timestamp, key = _get_key(timestamp=self.key_timestamp)
        cursor = connection.cursor()
        cursor.execute('select AES_DECRYPT(private_key, %s) '
                       'from addon_inapp where id=%s', [key, self.id])
        secret = cursor.fetchone()[0]
        if not secret:
            raise ValueError('Secret was empty! It either was not set or '
                             'the decryption key is wrong')
        return str(secret)  # make sure it is in bytes

    def has_private_key(self):
        return bool(self._encrypted_private_key)

    def set_private_key(self, raw_value):
        """Store the private key in the database."""
        if isinstance(raw_value, unicode):
            raw_value = raw_value.encode('ascii')
        timestamp, key = _get_key()
        cursor = connection.cursor()
        cursor.execute('UPDATE addon_inapp SET '
                       'private_key = AES_ENCRYPT(%s, %s), '
                       'key_timestamp = %s WHERE id=%s',
                       [raw_value, key, timestamp, self.id])

    @classmethod
    def any_active(cls, addon, exclude_config=None):
        """
        Tells you if there are any active keys for this addon besides the
        config under edit.
        """
        qs = cls.objects.filter(addon=addon, status=amo.INAPP_STATUS_ACTIVE)
        if exclude_config:
            qs = qs.exclude(pk=exclude_config)
        return qs.exists()

    def save(self, *args, **kw):
        current = InappConfig.any_active(self.addon, exclude_config=self.pk)
        if current:
            raise ValueError('You can only have one active config')
        super(InappConfig, self).save(*args, **kw)

    @classmethod
    def generate_public_key(cls, tries=0, max_tries=40):

        def gen_key():
            """Generate a simple (non-secret) public key."""
            key = []
            chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            for i in xrange(20):
                key.append(random.choice(chars))
            return ''.join(key)

        for key in limited_keygen(gen_key, max_tries):
            if cls.objects.filter(public_key=key).count() == 0:
                return key

    @classmethod
    def generate_private_key(cls, max_tries=40):
        """Generate a random 64 character secret key."""

        timestamp, enc_key = _get_key()
        for key in limited_keygen(lambda: generate_key(32), max_tries):
            cursor = connection.cursor()
            cursor.execute('select count(*) from addon_inapp where '
                           'private_key = AES_ENCRYPT(%s, %s) ',
                           [key, enc_key])
            if cursor.fetchone()[0] == 0:
                return key

    def app_protocol(self):
        """Protocol to use when posting to this app domain."""
        if settings.INAPP_REQUIRE_HTTPS:
            return 'https'
        else:
            return 'https' if self.is_https else 'http'

    def image_url(self, product_img_url=None):
        """URL for the cached product image at product_img_url.

        The product_img_url is the optional JWT key at
        jwt['request']['imageURL']
        """
        qs = self.images.filter(config=self, image_url=product_img_url,
                                valid=True)
        if product_img_url and qs.count():
            return qs.get().url()
        else:
            return InappImage.default_image_url()


def limited_keygen(gen_key, max_tries):
    for try_ in range(max_tries):
        yield gen_key()
    raise TooManyKeyGenAttempts('exceeded %s tries to generate a unique key'
                                % max_tries)


def _get_key(timestamp=None):
    """Get (timestamp, key) used to encrypt data in the db."""
    try:
        if not timestamp:
            # Get the most recent date in settings.
            timestamp = sorted(settings.INAPP_KEY_PATHS.keys())[-1]
        keypath = settings.INAPP_KEY_PATHS[timestamp]
    except (IndexError, KeyError), exc:
        ms = 'key %r not in INAPP_KEY_PATHS (%s)' % (timestamp, exc)
        exc.args = (ms,) + exc.args[1:]
        raise
    if (not settings.DEBUG and
        keypath.endswith('inapp-sample-pay.key')):
        raise EnvironmentError('encryption key looks like the one we '
                               'committed to the repo!')
    with open(keypath, 'rb') as fp:
        return timestamp, fp.read()


class InappPayLog(amo.models.ModelBase):
    action = models.IntegerField()
    session_key = models.CharField(max_length=64, null=True, blank=True)
    app_public_key = models.CharField(max_length=255, null=True, blank=True)
    user = models.ForeignKey('users.UserProfile', null=True, blank=True)
    config = models.ForeignKey(InappConfig, null=True, blank=True)
    exception = models.IntegerField(null=True, blank=True)

    # Magic numbers:
    _actions = {'PAY_START': 1,
                'PAY': 2,
                'PAY_COMPLETE': 3,
                'PAY_CANCEL': 4,
                'PAY_ERROR': 5,
                'EXCEPTION': 6}
    _exceptions = {'InappPaymentError': 1,
                   'AppPaymentsDisabled': 2,
                   'RequestExpired': 3,
                   'RequestVerificationError': 4,
                   'UnknownAppError': 5,
                   'AppPaymentsRevoked': 6,
                   'InvalidRequest': 7}

    class Meta:
        db_table = 'addon_inapp_log'

    @classmethod
    def log(cls, request, action_name, user=None, config=None, exc_class=None,
            app_public_key=None):
        if action_name == 'EXCEPTION':
            app = config.addon if config else 'unknown'
            inapp_cef.log(request, app, 'inapp_pay_error',
                          'Encountered exception during in-app '
                          'payment flow: %s' % (exc_class or 'unknown'),
                          severity=4)
        cls.objects.create(session_key=request.session.session_key,
                           user=user,
                           action=cls._actions[action_name],
                           config=config,
                           app_public_key=app_public_key,
                           exception=cls._exceptions[exc_class]
                                     if exc_class else None)


class InappPayment(amo.models.ModelBase):
    config = models.ForeignKey(InappConfig)
    contribution = models.ForeignKey('stats.Contribution',
                                     related_name='inapp_payment')
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    app_data = models.CharField(max_length=255, blank=True)

    def handle_chargeback(self, reason):
        """
        Hook to handle a payment chargeback.

        When a chargeback is received from a PayPal IPN
        for this payment's contribution, the hook is called.

        reason is either 'reversal' or 'refund'
        """
        from mkt.inapp_pay import tasks
        tasks.chargeback_notify.delay(self.pk, reason)

    class Meta:
        db_table = 'addon_inapp_payment'
        unique_together = ('config', 'contribution')


class InappPayNotice(amo.models.ModelBase):
    """In-app payment notification sent to the app."""
    notice = models.IntegerField(choices=amo.INAPP_NOTICE_CHOICES)
    payment = models.ForeignKey(InappPayment)
    url = models.CharField(max_length=255)
    success = models.BooleanField()  # App responded OK to notification.
    last_error = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'addon_inapp_notice'


class InappImage(amo.models.ModelBase):
    config = models.ForeignKey(InappConfig, related_name='images')
    image_url = models.CharField(max_length=255, db_index=True)
    image_format = models.CharField(max_length=4)
    valid = models.BooleanField(default=False, db_index=True)
    processed = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = 'addon_inapp_image'

    def absolute_image_url(self):
        if self.image_url.lower().startswith('http'):
            return self.image_url
        else:
            # Assume it is relative to the app.
            return urlparse.urlunparse((
                self.config.app_protocol(),
                self.config.addon.parsed_app_domain.netloc, self.image_url, '',
                '', ''))

    def path(self):
        return '/'.join((settings.INAPP_IMAGE_PATH, self._base_path()))

    @classmethod
    def default_image_url(cls):
        return '/'.join((settings.MEDIA_URL, 'img/mkt/glyphs/rocket.png'))

    def url(self):
        return '/'.join((settings.INAPP_IMAGE_URL, self._base_path()))

    def _base_path(self):
        ext = self.image_format.lower()
        if ext == 'jpeg':
            # The CDN only whitelists this extension.
            ext = 'jpg'
        return '%s/%s.%s' % (self.config.addon.pk, self.pk, ext)
