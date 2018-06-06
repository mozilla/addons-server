from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count

from olympia import amo
from olympia.addons.models import Version
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import chunked
from olympia.files.models import File


class Command(BaseCommand):
    help = 'Report conflicting files for search engine Addons'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--change', action='store_true',
            dest='change', help='Changes files to platform all.')
        parser.add_argument(
            '--report', action='store_true',
            dest='report', help='Reports files that might conflict.')

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
    print('Changing %s files' % len(files))
    for chunk in chunked(files, 100):
        for file in File.objects.no_cache().filter(pk__in=chunk):
            file.platform = amo.PLATFORM_ALL.id
            if not file.datestatuschanged:
                file.datestatuschanged = datetime.now()
            file.save()
            k += 1
            if not k % 50:
                print('... done %s' % k)


def report():
    versions = list(Version.objects.values_list('pk', flat=True)
                           .annotate(files_count=Count('files'))
                           .filter(addon__type=amo.ADDON_SEARCH)
                           .filter(files_count__gt=1))
    for chunk in chunked(versions, 100):
        for version in Version.objects.no_cache().filter(pk__in=chunk):
            print('Addon: %s, %s' % (version.addon.pk,
                                     version.addon.name))
            print('Version: %s - %s files' % (version.pk,
                                              version.files.count()))
            print('URL: %s' % reverse('devhub.versions.edit',
                                      args=[version.addon.slug,
                                            version.pk]))
            hashes = []
            for file in version.all_files:
                print('File: %s, %s' % (file.filename, file.hash))
                if file.hash in hashes:
                    print('...this hash is repeated, same file?')
                hashes.append(file.hash)
