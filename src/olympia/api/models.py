import os
import random

from django.db import models

from aesfield.field import AESField

from olympia.amo.models import ModelBase
from olympia.users.models import UserProfile


# These are identifiers for the type of API keys that can be stored
# in our database.
SYMMETRIC_JWT_TYPE = 1

API_KEY_TYPES = [SYMMETRIC_JWT_TYPE]


class APIKey(ModelBase):
    """
    A developer's key/secret pair to access the API.
    """

    user = models.ForeignKey(UserProfile, related_name='api_keys')

    # A user can only have one active key at the same time, it's enforced by
    # a unique db constraint. Since we keep old inactive keys though, nulls
    # need to be allowed (and we need to always set is_active=None instead of
    # is_active=False when revoking keys).
    is_active = models.NullBooleanField(default=True)
    type = models.PositiveIntegerField(
        choices=dict(zip(API_KEY_TYPES, API_KEY_TYPES)).items(), default=0
    )
    key = models.CharField(max_length=255, db_index=True, unique=True)
    # TODO: use RSA public keys instead? If we were to use JWT RSA keys
    # then we'd only need to store the public key.
    secret = AESField(aes_key='api_key:secret')

    class Meta:
        db_table = 'api_key'
        unique_together = (('user', 'is_active'),)

    def __unicode__(self):
        return u'<{cls} user={user}, type={type}, key={key} secret=...>'.format(
            cls=self.__class__.__name__,
            key=self.key,
            type=self.type,
            user=self.user,
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
                'a unique API key could not be found after {} tries'.format(
                    max_tries
                )
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
        return os.urandom(byte_length).encode('hex')
