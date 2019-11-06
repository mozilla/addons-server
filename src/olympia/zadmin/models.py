import json

from django.db import models


class Config(models.Model):
    """Sitewide settings."""

    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = u'config'

    def __str__(self):
        return self.key

    @property
    def json(self):
        try:
            return json.loads(self.value)
        except (TypeError, ValueError):
            return {}


def get_config(conf):
    try:
        return Config.objects.get(key=conf).value
    except Config.DoesNotExist:
        return None


def set_config(conf, value):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value
    cf.save()
