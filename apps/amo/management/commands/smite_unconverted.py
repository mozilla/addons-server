import logging

from django.core.management.base import BaseCommand

import path
from celery.task.sets import TaskSet

import bandwagon.tasks
import users.tasks
from amo.helpers import user_media_path

log = logging.getLogger('z.cmd')


suffix = '__unconverted'


class Command(BaseCommand):
    help = "Clean up __unconverted files"

    def handle(self, *args, **kw):
        z = ((user_media_path('collection_icons'), bandwagon.tasks.resize_icon),
             (user_media_path('userpics'), users.tasks.resize_photo))
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
