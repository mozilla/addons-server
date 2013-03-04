import logging
from optparse import make_option

from django.core.management.base import BaseCommand

from celery.task.sets import TaskSet

import amo
from addons.models import Webapp
from lib.crypto.packaged import sign


HELP = """\
Start tasks to re-sign web apps.

To specify which webapps to sign:

    `--webapps=1234,5678,...9012`

If omitted, all signed apps will be re-signed.
"""


log = logging.getLogger('z.addons')


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--webapps',
                    help='Webapp ids to process. Use commas to separate '
                         'multiple ids.'),
    )

    help = HELP

    def handle(self, *args, **kw):
        qs = Webapp.objects.filter(is_packaged=True, status=amo.STATUS_PUBLIC)
        if kw['webapps']:
            pks = [int(a.strip()) for a in kw['webapps'].split(',')]
            qs = qs.filter(pk__in=pks)
        ts = [sign.subtask(args=[webapp.current_version.pk],
                           kwargs={'resign': True}) for webapp in qs]
        TaskSet(ts).apply_async()
