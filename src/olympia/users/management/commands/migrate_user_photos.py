import os

from django.conf import settings
from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users.migrate_user_photos')


class Command(BaseCommand):
    help = 'Migrate user photos to new directory structure and remove orphaned ones'

    # Note: because avatars are only displayed on developer profiles and
    # heavily cached, we're directly migrating in-place without
    # backwards-compatibility - UserProfile.picture_dir implementation has
    # already been updated to point to the new location. There will be some
    # 404s until the migration is finished, but CDN caching should help avoid
    # some of them.

    def handle(self, *args, **options):
        basedirname = os.path.join(settings.MEDIA_ROOT, 'userpics')
        for dirname in os.listdir(basedirname):
            dirpath = os.path.join(basedirname, dirname)
            subdirs_count = os.stat(dirpath).st_nlink - 2
            log.info(
                'Migrating files inside %s/ (%d subdirectories)', dirname, subdirs_count
            )
            for subdirname in os.listdir(dirpath):
                for filename in os.listdir(
                    os.path.join(basedirname, dirname, subdirname)
                ):
                    fullpath = os.path.join(basedirname, dirname, subdirname, filename)
                    user = None
                    try:
                        # Valid filenames are {pk}.png or {pk}_original.png
                        pk = int(
                            os.path.splitext(filename)[0].removesuffix('_original')
                        )
                        user = (
                            UserProfile.objects.only('pk')
                            .filter(pk=pk, deleted=False)
                            .get()
                        )
                    except (ValueError, UserProfile.DoesNotExist):
                        log.info('Deleting orphaned file %s', fullpath)
                        os.remove(fullpath)
                        continue
                    log.info('Migrating file %s', fullpath)
                    os.makedirs(user.picture_dir, exist_ok=True)
                    new_path = os.path.join(user.picture_dir, filename)
                    os.rename(fullpath, new_path)
