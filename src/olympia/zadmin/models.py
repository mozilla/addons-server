import json

from django.db import models

from olympia.amo.models import ModelBase
import olympia.core.logger


log = olympia.core.logger.getLogger('z.zadmin')


class Config(ModelBase):
    """Sitewide settings."""

    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = 'config'

    def __str__(self):
        return self.key


def get_config(key, default=None, *, json_value=False, int_value=False):
    try:
        value = Config.objects.get(key=key).value
    except Config.DoesNotExist:
        value = default
    try:
        if json_value:
            value = json.loads(value)
        elif int_value:
            value = int(value)
    except (TypeError, ValueError):
        log.error('[%s] config key appears to not be set correctly (%s)', key, value)
        value = default
    return value


def set_config(conf, value, *, json_value=False):
    cf, created = Config.objects.get_or_create(key=conf)
    cf.value = value if not json_value else json.dumps(value)
    cf.save()
