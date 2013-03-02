import os
import time

from django.db import models

from amo.models import ModelBase


REQUEST_TOKEN = 0
ACCESS_TOKEN = 1
TOKEN_TYPES = ((REQUEST_TOKEN, u'Request'), (ACCESS_TOKEN, u'Access'))


class Access(ModelBase):
    key = models.CharField(max_length=255, unique=True)
    secret = models.CharField(max_length=255)
    user = models.ForeignKey('auth.User')
    redirect_uri = models.CharField(max_length=255)
    app_name = models.CharField(max_length=255)

    class Meta:
        db_table = 'api_access'


class Token(ModelBase):
    token_type = models.SmallIntegerField(choices=TOKEN_TYPES)
    creds = models.ForeignKey(Access)
    key = models.CharField(max_length=255)
    secret = models.CharField(max_length=255)
    timestamp = models.IntegerField()
    user = models.ForeignKey('auth.User', null=True)
    verifier = models.CharField(max_length=255, null=True)

    class Meta:
        db_table = 'oauth_token'

    @classmethod
    def generate_new(cls, token_type, creds, user=None):
        return cls.objects.create(
            token_type=token_type,
            creds=creds,
            key=generate(),
            secret=generate(),
            timestamp=time.time(),
            verifier=generate() if token_type == REQUEST_TOKEN else None,
            user=user)


class Nonce(ModelBase):
    nonce = models.CharField(max_length=128)
    timestamp = models.IntegerField()
    client_key = models.CharField(max_length=255)
    request_token = models.CharField(max_length=128, null=True)
    access_token = models.CharField(max_length=128, null=True)

    class Meta:
        db_table = 'oauth_nonce'
        unique_together = ('nonce', 'timestamp', 'client_key',
                           'request_token', 'access_token')


def generate():
    return os.urandom(64).encode('hex')
