#!/usr/bin/env python

from addons.models import Addon
from editors.models import RereviewQueueTheme

import olympia.core.logger


log = olympia.core.logger.getLogger('z.task')


def run():
    """Delete RereviewQueueTheme objects whose themes did not cascade delete
    with add-on. Came about from setting on_delete to invalid value in
    model."""
    for rqt in RereviewQueueTheme.objects.all():
        try:
            rqt.theme.addon
        except Addon.DoesNotExist:
            log.info('[Theme %s] Deleting rereview_queue_theme,'
                     ' add-on does not exist.' % rqt.theme.id)
            rqt.delete()
