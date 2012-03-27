import base64
import os
import random

from django.db import models

from tower import ugettext_lazy as _lazy

import amo


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
    private_key = models.CharField(max_length=255, unique=True)
    public_key = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.PositiveIntegerField(choices=amo.INAPP_STATUS_CHOICES,
                                         default=amo.INAPP_STATUS_INACTIVE,
                                         db_index=True)

    class Meta:
        db_table = 'addon_inapp'

    def is_active(self):
        return self.status == amo.INAPP_STATUS_ACTIVE

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.status)

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

        def gen_key():
            """Generate a random 43 character secret key."""
            key = os.urandom(32)  # 256 bit
            return base64.b64encode(key).rstrip('=')  # strip off padding

        for key in limited_keygen(gen_key, max_tries):
            if cls.objects.filter(private_key=key).count() == 0:
                return key


def limited_keygen(gen_key, max_tries):
    for try_ in range(max_tries):
        yield gen_key()
    raise TooManyKeyGenAttempts('exceeded %s tries to generate a unique key'
                                % max_tries)


class InappPayLog(amo.models.ModelBase):
    action = models.IntegerField()
    session_key = models.CharField(max_length=64)
    app_public_key = models.CharField(max_length=255, null=True, blank=True)
    user = models.ForeignKey('users.UserProfile', null=True, blank=True)
    config = models.ForeignKey(InappConfig, null=True, blank=True)
    exception = models.IntegerField(null=True, blank=True)

    # Magic numbers:
    _actions = {'PAY_START': 1,
                'PAY': 2,
                'EXCEPTION': 3}
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
        cls.objects.create(session_key=request.session.session_key,
                           user=user,
                           action=cls._actions[action_name],
                           config=config,
                           app_public_key=app_public_key,
                           exception=cls._exceptions[exc_class]
                                     if exc_class else None)
