import logging

from django.conf import settings
from django.core.management.base import BaseCommand

import path
from celery.task.sets import TaskSet

import bandwagon.tasks
import users.tasks

log = logging.getLogger('z.cmd')


suffix = '__unconverted'


class Command(BaseCommand):
    help = "Clean up __unconverted files"

    def handle(self, *args, **kw):
        z = ((settings.COLLECTIONS_ICON_PATH, bandwagon.tasks.resize_icon),
             (settings.USERPICS_PATH, users.tasks.resize_photo))
        for base, task in z:
            self.fix(base, task)

    def fix(self, base, task):
        print 'Searching the nfs...'
        files = list(path.path(base).walkfiles('*%s' % suffix))
        print '%s busted files under %s.' % (len(files), base)
        ts = []
        for src in files:
            dst = src.replace(suffix, '')
            log.info('Resizing %s to %s' % (src, dst))
            ts.append(task.subtask(args=[src, dst]))
        TaskSet(ts).apply_async()
