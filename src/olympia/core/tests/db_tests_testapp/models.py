from django.db import models

from olympia.amo.models import ModelBase


class TestRegularCharField(ModelBase):
    __test__ = False

    name = models.CharField(max_length=255)
