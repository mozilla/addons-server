import time

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.addons.models import AddonCategory
from olympia.constants.categories import CATEGORIES_BY_ID


# Mapping between old Android categories and new global ones.
MAPPING_BY_ID = {
    145: 73,  # 'device-features-location' —> 'other'
    151: 73,  # 'experimental' —> 'other'
    147: 1,  # 'feeds-news-blogging' —> 'feeds-news-blogging'
    144: 73,  # 'performance' —> 'other'
    143: 38,  # 'photos-media' —> 'photos-music-videos'
    149: 12,  # 'security-privacy' —> 'privacy-security'
    150: 141,  # 'shopping' —> 'shopping'
    148: 71,  # 'social-networking' —> 'social-communication'
    146: 142,  # 'sports-games' —> 'games-entertainment'
    152: 14,  # 'user-interface' —> 'appearance'
    153: 73,  # 'other' —> 'other
}

log = olympia.core.logger.getLogger('z.addons.update_and_clean_categories')


class Command(BaseCommand):
    BATCH_SIZE = 1000

    def add_new_categories_for_old_android_categories(self):
        for old_category_id, new_category_id in MAPPING_BY_ID.items():
            addon_ids = AddonCategory.objects.filter(
                category_id=old_category_id
            ).values_list('addon_id', flat=True)
            addon_categories = [
                AddonCategory(category_id=new_category_id, addon_id=addon_id)
                for addon_id in addon_ids
            ]
            # We can't run a single UPDATE query, because we might run into
            # constraint violations, as we could potentially force an add-on to
            # have the same category twice. To work around that we create new
            # categories instead in bulk, ignoring conflicts.
            # The old extra categories will be deleted later.
            objs = AddonCategory.objects.bulk_create(
                addon_categories,
                batch_size=self.BATCH_SIZE,
                ignore_conflicts=True,
            )
            log.info('Created (or ignored) %d AddonCategory rows', len(objs))
        log.info('Done updating old android categories')

    def delete_old_categories(self):
        qs = AddonCategory.objects.exclude(
            category_id__in=list(CATEGORIES_BY_ID.keys())
        )
        threshold = qs.order_by('-pk').values_list('pk', flat=True).first()
        ceiling = qs.order_by('pk').values_list('pk', flat=True).first()
        count = 0
        while threshold and ceiling and threshold >= ceiling:
            print(f'In loop {threshold}')
            try:
                # Delete by batch. Django doesn't support deleting with a limit
                # and offset, but that's inefficient anyway, so we do it by pk,
                # deleting _at most_ BATCH_SIZE per iteration.
                threshold -= self.BATCH_SIZE
                loop_count = qs.filter(
                    pk__gte=threshold, pk__lte=threshold + self.BATCH_SIZE
                ).delete()[0]
            except IndexError:
                break
            log.info('Deleted %d AddonCategory rows', loop_count)
            if loop_count:
                time.sleep(1)
            count += loop_count
        log.info('Done deleting %d obsolete categories', count)

    def handle(self, *args, **kwargs):
        self.add_new_categories_for_old_android_categories()
        self.delete_old_categories()
