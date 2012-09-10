import os

from django.db import models

from amo.models import ModelBase


class Access(ModelBase):
    key = models.CharField(max_length=255, unique=True)
    secret = models.CharField(max_length=255)
    user = models.ForeignKey('auth.User')

    class Meta:
        db_table = 'api_access'


def generate():
    return os.urandom(64).encode('hex')
