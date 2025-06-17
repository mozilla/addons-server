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


def get_config(config_key):
    if not hasattr(config_key, 'key'):
        config_key = amo.config_keys.ConfigKey(config_key)
    assert config_key.key in amo.config_keys.KEYS

    try:
        value = Config.objects.get(key=config_key.key).value
        return config_key.load(value)
    except Config.DoesNotExist:
        pass
    except (TypeError, ValueError):
        log.error(
            '[%s] config key appears to not be set correctly (%s)',
            config_key.key,
            value,
        )
    return config_key.default


def set_config(config_key, value):
    if not hasattr(config_key, 'key'):
        config_key = amo.config_keys.ConfigKey(config_key)
    assert config_key.key in amo.config_keys.KEYS

    cf, _ = Config.objects.get_or_create(key=config_key.key)
    cf.value = config_key.dump(value)
    cf.save()
