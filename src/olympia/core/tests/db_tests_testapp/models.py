from django.db import models

from olympia.amo.models import ModelBase


class TestRegularCharField(models.Model):
    name = models.CharField(max_length=255)
