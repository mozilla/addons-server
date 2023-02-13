import os

from datetime import datetime, timedelta
from os import scandir

from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.addons.models import Addon, Preview
from olympia.amo.utils import id_to_path
from olympia.blocklist.utils import datetime_to_ts
from olympia.files.models import File
from olympia.hero.models import PrimaryHeroImage
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionPreview


def get_modified_folders(since, *, path, manager, datefield, id_to_path_breadth):
    qs = manager.filter(**{f'{datefield}__gt': since}).values_list('id', flat=True)
    return [
        os.path.join(path, id_to_path(id_, breadth=id_to_path_breadth), '')
        for id_ in qs
    ]


def collect_user_pics(since):
    return get_modified_folders(
        since,
        path=os.path.join(settings.MEDIA_ROOT, 'userpics'),
        manager=UserProfile.objects,
        datefield='modified',
        id_to_path_breadth=2,
    )


def collect_files(since):
    path = settings.ADDONS_PATH
    qs = File.objects.filter(modified__gt=since).values_list(
        'version__addon_id', flat=True
    )
    return list({os.path.join(path, id_to_path(id_, breadth=2), '') for id_ in qs})


def collect_sources(since):
    return get_modified_folders(
        since,
        path=os.path.join(settings.MEDIA_ROOT, 'version_source'),
        manager=Version.unfiltered,
        datefield='modified',
        id_to_path_breadth=1,
    )


def get_previews(since, path, manager):
    out = set()
    qs = manager.filter(created__gt=since).values_list('id', flat=True)
    for preview_id in qs:
        subdir = str(preview_id // 1000)
        out = out | {
            os.path.join(path, 'thumbs', subdir, ''),
            os.path.join(path, 'full', subdir, ''),
            os.path.join(path, 'original', subdir, ''),
        }
    return list(out)


def collect_addon_previews(since):
    return get_previews(
        since, os.path.join(settings.MEDIA_ROOT, 'previews'), Preview.objects
    )


def collect_theme_previews(since):
    return get_previews(
        since,
        os.path.join(settings.MEDIA_ROOT, 'version-previews'),
        VersionPreview.objects,
    )


def collect_addon_icons(since):
    path = os.path.join(settings.MEDIA_ROOT, 'addon_icons')
    qs = Addon.unfiltered.filter(modified__gt=since).values_list('id', flat=True)
    return list({os.path.join(path, str(preview_id // 1000), '') for preview_id in qs})


def collect_editoral(since):
    return (
        [os.path.join(settings.MEDIA_ROOT, 'hero-featured-image')]
        if PrimaryHeroImage.objects.filter(modified__gt=since).exists()
        else []
    )


def collect_git(since):
    path = settings.GIT_FILE_STORAGE_PATH
    qs = File.objects.filter(modified__gt=since).values_list(
        'version__addon_id', flat=True
    )
    return list(
        {
            os.path.join(path, id_to_path(addon_id, breadth=2), 'addon', '')
            for addon_id in qs
        }
    )


def collect_blocklist(since):
    path = settings.MLBF_STORAGE_PATH
    since_ts = datetime_to_ts(since)
    return [
        file_.path
        for file_ in scandir(path)
        if file_.is_dir() and file_.name.isdigit() and int(file_.name) >= since_ts
    ]


class Command(BaseCommand):
    help = (
        'Get folders containing files that have changed on the filesystem in the past '
        'X seconds'
    )

    def add_arguments(self, parser):
        parser.add_argument('since', type=int)

    def get_collectors(self):
        return [
            collect_user_pics,
            collect_files,
            collect_sources,
            collect_addon_previews,
            collect_theme_previews,
            collect_addon_icons,
            collect_editoral,
            collect_git,
            collect_blocklist,
        ]

    def handle(self, *args, **options):
        since = datetime.now() - timedelta(seconds=options['since'])
        for func in self.get_collectors():
            items = func(since)
            [self.stdout.write(os.path.normpath(item)) for item in items]
