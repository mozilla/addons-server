from django.db import models

from . import tasks


def flush_front_end_cache(sender, instance, **kwargs):
    furls = getattr(instance, 'flush_urls', None)

    urls = furls() if hasattr(furls, '__call__') else furls
    tasks.flush_front_end_cache_urls.apply_async(args=[urls])

models.signals.post_save.connect(flush_front_end_cache)
models.signals.post_delete.connect(flush_front_end_cache)
