import json

from django.db import models


class Config(models.Model):
    """Sitewide settings."""
    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = u'config'

    @property
    def json(self):
        return json.loads(self.value)
