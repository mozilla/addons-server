from optparse import make_option
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count

from addons.models import Version
import amo
from amo.utils import chunked
from amo.urlresolvers import reverse
from files.models import File, Platform


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--change', action='store_true',
                    dest='change', help='Changes files to platform all.'),
        make_option('--report', action='store_true',
                    dest='report', help='Reports files that might conflict.'),
    )
    help = 'Report conflicting files for search engine Addons'

    def handle(self, *args, **options):
        if options.get('change', False):
            change()
        if options.get('report', False):
            report()


def change():
    files = list(File.objects.values_list('pk', flat=True)
                     .filter(version__addon__type=amo.ADDON_SEARCH)
                     .exclude(platform=amo.PLATFORM_ALL.id))
    k = 0
    print 'Changing %s files' % len(files)
    for chunk in chunked(files, 100):
        for file in File.uncached.filter(pk__in=chunk):
            file.platform_id = amo.PLATFORM_ALL.id
            if not file.datestatuschanged:
                file.datestatuschanged = datetime.now()
            file.save()
            k += 1
            if not k % 50:
                print '... done %s' % k


def report():
    versions = list(Version.objects.values_list('pk', flat=True)
                           .annotate(files_count=Count('files'))
                           .filter(addon__type=amo.ADDON_SEARCH)
                           .filter(files_count__gt=1))
    for chunk in chunked(versions, 100):
        for version in Version.uncached.filter(pk__in=chunk):
            print 'Addon: %s, %s' % (version.addon.pk,
                                     version.addon.name)
            print 'Version: %s - %s files' % (version.pk,
                                              version.files.count())
            print 'URL: %s' % reverse('devhub.versions.edit',
                                      args=[version.addon.pk,
                                            version.pk])
            hashes = []
            for file in version.all_files:
                print 'File: %s, %s' % (file.filename, file.hash)
                if file.hash in hashes:
                    print '...this hash is repeated, same file?'
                hashes.append(file.hash)

            print
