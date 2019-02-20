from django.db import models


class TestRegularCharField(models.Model):
    name = models.CharField(max_length=255)
