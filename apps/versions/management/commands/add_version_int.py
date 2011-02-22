from django.core.management.base import BaseCommand

from celery.messaging import establish_connection

from amo.utils import chunked
from versions.models import Version
from versions.tasks import add_version_int


# TODO(andym): remove this when versions all done.
class Command(BaseCommand):
    help = 'Upgrade the version model to have a version_int'

    def handle(self, *args, **kw):
        qs = Version.objects.filter(version_int=None)
        print 'Found %s versions that need updating' % qs.count()
        with establish_connection() as conn:
            for pks in chunked(list(qs.values_list('pk', flat=True)), 1000):
                add_version_int.delay(pks)
        print '... added to celery.'
