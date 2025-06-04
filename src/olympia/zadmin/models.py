import json

from django.db import models

import olympia.core.logger
from olympia import amo


log = olympia.core.logger.getLogger('z.zadmin')


class Config(models.Model):
    """Sitewide settings."""

    key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = 'config'

    def __str__(self):
        return self.key


def get_config(key):
    if isinstance(key, tuple):
        key, val_type, default = key
    else:
        val_type = str
        default = None
    assert key in amo.config_keys.KEYS

    try:
        value = Config.objects.get(key=key).value
    except Config.DoesNotExist:
        return default
    try:
        if val_type is json:
            value = json.loads(value)
        elif val_type is int:
            value = int(value)
        return value
    except (TypeError, ValueError):
        log.error('[%s] config key appears to not be set correctly (%s)', key, value)
        return default


def set_config(key, value):
    if isinstance(key, tuple):
        key, val_type, _ = key
    else:
        val_type = str
    assert key in amo.config_keys.KEYS

    cf, _ = Config.objects.get_or_create(key=key)
    cf.value = value if val_type is not json else json.dumps(value)
    cf.save()
