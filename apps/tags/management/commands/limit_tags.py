from django.core.management.base import BaseCommand
from django.db.models import Count

from addons.models import Addon
from amo.utils import chunked

MAX_TAGS = 20


def handle_addon(addon):
    count = addon.addon_tags.count()
    if count > MAX_TAGS:
        authors = addon.authors.values_list('pk', flat=True)
        keep = list(addon.addon_tags.no_cache()
                    .no_transforms()
                    .values_list('pk', flat=True)
                    .filter(tag__blacklisted=False)
                    .filter(user__in=authors)
                    .order_by('user__created', 'tag__created')
                    )[:MAX_TAGS]
        if len(keep) < MAX_TAGS:
            keep.extend(list(addon.addon_tags.no_cache()
                        .no_transforms()
                        .values_list('pk', flat=True)
                        .filter(tag__blacklisted=False)
                        .exclude(user__in=authors)
                        .order_by('user__created', 'tag__created')
                        )[:MAX_TAGS - len(keep)])

        addon.addon_tags.exclude(pk__in=keep).delete()


class Command(BaseCommand):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=600685
    help = 'Migration to limit tags to %s per addon as per 600685' % MAX_TAGS

    def handle(self, *args, **kw):
        pks = list(Addon.uncached.values_list("pk", flat=True)
                        .annotate(addon_tags_count=Count('addon_tags'))
                        .filter(addon_tags_count__gt=MAX_TAGS))

        k, count = 0, len(pks)
        print "Found: %s addons that need altering" % count
        for chunk in chunked(pks, 100):
            addons = Addon.uncached.filter(pk__in=chunk)
            for addon in addons:
                handle_addon(addon)
                k += 1
                if not k % 50:
                    print "Completed: %s" % k
