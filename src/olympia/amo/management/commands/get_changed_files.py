import os

from datetime import datetime, timedelta
from os import scandir

from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.addons.models import Addon, Preview
from olympia.amo.utils import id_to_path
from olympia.blocklist.utils import datetime_to_ts
from olympia.files.models import File
from olympia.git.utils import AddonGitRepository
from olympia.hero.models import PrimaryHeroImage
from olympia.users.models import UserProfile
from olympia.versions.models import Version, VersionPreview


def collect_user_pics(since):
    qs = UserProfile.objects.filter(modified__gt=since).only('id', 'username')
    return [user.picture_dir for user in qs.iterator()]


def collect_files(since):
    path = settings.ADDONS_PATH
    id_iter = (
        File.objects.filter(modified__gt=since)
        .values_list('version__addon_id', flat=True)
        .iterator()
    )
    return list({os.path.join(path, id_to_path(id_, breadth=2)) for id_ in id_iter})


def collect_sources(since):
    path = os.path.join(settings.MEDIA_ROOT, 'version_source')
    id_iter = Version.unfiltered.filter(modified__gt=since).values_list('id', flat=True)
    return [os.path.join(path, id_to_path(id_, breadth=1)) for id_ in id_iter]


def _get_previews(since, PreviewModel):
    out = set()
    qs = PreviewModel.objects.filter(created__gt=since).only('id', 'sizes')
    for preview in qs.iterator():
        out = out | {
            os.path.dirname(preview.thumbnail_path),
            os.path.dirname(preview.image_path),
            os.path.dirname(preview.original_path),
        }
    return list(out)


def collect_addon_previews(since):
    return _get_previews(since, Preview)


def collect_theme_previews(since):
    return _get_previews(since, VersionPreview)


def collect_addon_icons(since):
    qs = Addon.unfiltered.filter(modified__gt=since).only('id')
    return list({addon.get_icon_dir() for addon in qs.iterator()})


def collect_editoral(since):
    return (
        [os.path.join(settings.MEDIA_ROOT, 'hero-featured-image')]
        if PrimaryHeroImage.objects.filter(modified__gt=since).exists()
        else []
    )


def collect_git(since):
    qs_iter = (
        File.objects.filter(modified__gt=since)
        .values_list('version__addon_id', flat=True)
        .iterator()
    )
    return list(
        {AddonGitRepository(addon_id).git_repository_path for addon_id in qs_iter}
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
