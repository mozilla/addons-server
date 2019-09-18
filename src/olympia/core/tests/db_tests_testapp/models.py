from django.db import models


class TestRegularCharField(models.Model):
    __test__ = False

    name = models.CharField(max_length=255)
