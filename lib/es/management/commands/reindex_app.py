"""
A Marketplace only command to re-index a specific app or apps.

Call like:

    ./manage.py reindex_app --apps=1234

Or call with a comma separated list of ids:

    ./manage.py reindex_app --apps=1234,2345,3456

"""
import logging
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from mkt.webapps.tasks import index_webapps


log = logging.getLogger('z.elasticsearch')


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--apps',
                    help='Webapp ids to process. Use commas to separate '
                         'multiple ids.'),
    )

    help = __doc__

    def handle(self, *args, **kw):
        apps = kw.get('apps')
        if not apps:
            raise CommandError('The --apps option is required.')

        ids = [int(a.strip()) for a in apps.split(',')]
        index_webapps.delay(ids)
