from optparse import make_option

from django.core.management.base import BaseCommand

from devhub.perf import start_perf_test
from files.models import File


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--os', action='store', default='win32',
                    help='Operating system to run performance tests on. '
                         'See wiki docs for recognized values.'),
        make_option('--firefox', action='store', default='firefox4.0',
                    help='The release of firefox to be tested against. '
                         'See wiki docs for recognized values.'),
        make_option('--file-id', action='store',
                    dest='file_id',
                    help='ID of the addon file to test.'),
    )
    help = "Test the performance of an addon."

    def handle(self, *args, **options):
        start_perf_test(File.objects.get(pk=options['file_id']),
                        options['os'], options['firefox'])
        print 'Tests started...'
