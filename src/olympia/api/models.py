import binascii
import os
import random

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.crypto import constant_time_compare, get_random_string
from django.utils.encoding import force_str
from django.utils.translation import gettext

from aesfield.field import AESField

from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import send_mail_jinja
from olympia.users.models import UserProfile


# These are identifiers for the type of API keys that can be stored
# in our database.
SYMMETRIC_JWT_TYPE = 1

API_KEY_TYPES = [
    SYMMETRIC_JWT_TYPE,
]


class APIKey(ModelBase):
    """
    A developer's key/secret pair to access the API.
    """

    id = PositiveAutoField(primary_key=True)
    user = models.ForeignKey(
        UserProfile, related_name='api_keys', on_delete=models.CASCADE
    )

    # A user can only have one active key at the same time, it's enforced by
    # a unique db constraint. Since we keep old inactive keys though, nulls
    # need to be allowed (and we need to always set is_active=None instead of
    # is_active=False when revoking keys).
    is_active = models.BooleanField(default=True, null=True)
    type = models.PositiveIntegerField(
        choices=dict(zip(API_KEY_TYPES, API_KEY_TYPES)).items(), default=0
    )
    key = models.CharField(max_length=255, db_index=True, unique=True)
    # TODO: use RSA public keys instead? If we were to use JWT RSA keys
    # then we'd only need to store the public key.
    secret = AESField(aes_key='api_key:secret')

    class Meta:
        db_table = 'api_key'
        indexes = [
            models.Index(fields=('user',), name='api_key_user_id'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('user', 'is_active'), name='user_id'),
        ]

    def __str__(self):
        return '<{cls} user={user}, type={type}, key={key} secret=...>'.format(
            cls=self.__class__.__name__, key=self.key, type=self.type, user=self.user
        )

    @classmethod
    def get_jwt_key(cls, **kwargs):
        """
        Return a single active APIKey instance for a given user or key.
        """
        kwargs['is_active'] = True
        return cls.objects.get(type=SYMMETRIC_JWT_TYPE, **kwargs)

    @classmethod
    def new_jwt_credentials(cls, user):
        """
        Generates a new key/secret pair suitable for symmetric JWT signing.

        This method must be run within a db transaction.
        Returns an instance of APIKey.
        """
        key = cls.get_unique_key('user:{}:'.format(user.pk))
        return cls.objects.create(
            key=key,
            secret=cls.generate_secret(32),
            type=SYMMETRIC_JWT_TYPE,
            user=user,
            is_active=True,
        )

    @classmethod
    def get_unique_key(cls, prefix, try_count=1, max_tries=1000):
        if try_count >= max_tries:
            raise RuntimeError(
                'a unique API key could not be found after {} tries'.format(max_tries)
            )

        key = '{}{}'.format(prefix, random.randint(0, 999))
        if cls.objects.filter(key=key).exists():
            return cls.get_unique_key(
                prefix, try_count=try_count + 1, max_tries=max_tries
            )
        return key

    @staticmethod
    def generate_secret(byte_length):
        """
        Return a true random ascii string containing byte_length of randomness.

        The resulting key is suitable for cryptography.
        The key will be hex encoded which means it will be twice as long
        as byte_length, i.e. 40 random bytes yields an 80 byte string.

        byte_length must be at least 32.
        """
        if byte_length < 32:  # at least 256 bit
            raise ValueError(
                '{} is too short; secrets must be longer than 32 bytes'.format(
                    byte_length
                )
            )
        return force_str(binascii.b2a_hex(os.urandom(byte_length)))


class APIKeyConfirmation(ModelBase):
    user = models.OneToOneField(UserProfile, primary_key=True, on_delete=models.CASCADE)
    token = models.CharField(max_length=20)
    confirmed_once = models.BooleanField(default=False)

    @staticmethod
    def generate_token():
        """
        Generate token for API Key Confirmation mechanism.

        Returns a random 20 characters string (using a-z, A-Z, 0-9 characters).
        """
        return get_random_string(20)

    def send_confirmation_email(self):
        context = {
            'api_key_confirmation_link': (
                absolutify(reverse('devhub.api_key')) + f'?token={self.token}'
            ),
            'domain': settings.DOMAIN,
        }
        return send_mail_jinja(
            gettext('Confirmation for developer API keys'),
            'devhub/emails/api_key_confirmation.ltxt',
            context,
            recipient_list=[self.user.email],
            countdown=settings.API_KEY_CONFIRMATION_DELAY,
        )

    def is_token_valid(self, token):
        """
        Compare token passed in argument with the one on the instance.
        """
        return constant_time_compare(self.token, token)
