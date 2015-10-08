import os
import time

from django.db import models

from aesfield.field import AESField

from users.models import UserProfile


KEY_SIZE = 18
SECRET_SIZE = 32
VERIFIER_SIZE = 10
CONSUMER_STATES = (
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('canceled', 'Canceled'),
    ('rejected', 'Rejected')
)
REQUEST_TOKEN = 1
ACCESS_TOKEN = 2
TOKEN_TYPES = ((REQUEST_TOKEN, u'Request'), (ACCESS_TOKEN, u'Access'))


class Access(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()

    key = models.CharField(max_length=KEY_SIZE)
    secret = models.CharField(max_length=SECRET_SIZE)

    status = models.CharField(max_length=16, choices=CONSUMER_STATES,
                              default='pending')
    user = models.ForeignKey(UserProfile, null=True, blank=True,
                             related_name='drf_consumers')

    class Meta:
        db_table = 'piston_consumer'


class Token(models.Model):
    key = models.CharField(max_length=KEY_SIZE)
    secret = models.CharField(max_length=SECRET_SIZE)
    verifier = models.CharField(max_length=VERIFIER_SIZE)
    token_type = models.IntegerField(choices=TOKEN_TYPES)
    timestamp = models.IntegerField(default=long(time.time()))
    is_approved = models.BooleanField(default=False)

    user = models.ForeignKey(UserProfile, null=True, blank=True,
                             related_name='drf_tokens')
    consumer = models.ForeignKey(Access)

    callback = models.CharField(max_length=255, null=True, blank=True)
    callback_confirmed = models.BooleanField(default=False)

    class Meta:
        db_table = 'piston_token'

    @classmethod
    def generate_new(cls, token_type, creds, user=None):
        return cls.objects.create(
            token_type=token_type,
            consumer=creds,
            key=generate(),
            secret=generate(),
            timestamp=time.time(),
            verifier=generate() if token_type == REQUEST_TOKEN else None,
            user=user)


class Nonce(models.Model):
    token_key = models.CharField(max_length=KEY_SIZE, null=True)
    consumer_key = models.CharField(max_length=KEY_SIZE, null=True)
    key = models.CharField(max_length=255)

    class Meta:
        db_table = 'piston_nonce'
        unique_together = ('token_key', 'consumer_key', 'key')


# These are identifiers for the type of API keys that can be stored
# in our database.
SYMMETRIC_JWT_TYPE = 1

API_KEY_TYPES = [
    SYMMETRIC_JWT_TYPE,
]


class APIKey(models.Model):
    """
    A developer's key/secret pair to access the API.
    """
    user = models.ForeignKey(UserProfile, related_name='api_keys')
    type = models.PositiveIntegerField(
        choices=dict(zip(API_KEY_TYPES, API_KEY_TYPES)).items(), default=0)
    key = models.CharField(max_length=255, db_index=True, unique=True)
    # TODO: use RSA public keys instead? If we were to use JWT RSA keys
    # then we'd only need to store the public key.
    secret = AESField(aes_key='api_key:secret')

    class Meta:
        db_table = 'api_key'

    @classmethod
    def get_jwt_key(cls, **query):
        """
        Look up the config for a JWT key.
        """
        return cls.objects.get(type=SYMMETRIC_JWT_TYPE, **query)


def generate():
    return os.urandom(64).encode('hex')
