from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.addons.models import Addon, ReusedGUID, GUID_REUSE_FORMAT


log = olympia.core.logger.getLogger('z.amo.addons')


class Command(BaseCommand):
    help = (
        'Backfill the ReusedGuid model with guids of add-ons that have '
        'been deleted and their guid reused by a new add-on.'
    )

    def handle(self, *args, **options):
        startswith_guid = GUID_REUSE_FORMAT.format('')
        qs = Addon.unfiltered.filter(
            status=amo.STATUS_DELETED, guid__startswith=startswith_guid
        )
        addons = qs.values_list('pk', 'guid').order_by('id')
        addons_pks = list(pk for pk, _ in addons)
        log.info('Add-ons found needing backfill: %s.', addons_pks)
        other_previous_pks = {}
        for pk, fake_guid in addons:
            reused_by_pk = int(fake_guid[18:])
            pks_to_add = other_previous_pks.get(pk, []) + [pk]
            if reused_by_pk in addons_pks:
                # if it's in addon_pks then it's been reused again, so defer
                # until we have the last reused instance.
                log.info(
                    'Addon id [%s] also reused, so deferring %s.',
                    reused_by_pk,
                    pks_to_add,
                )
                other_previous_pks[reused_by_pk] = pks_to_add
            else:
                try:
                    real_guid = Addon.unfiltered.get(pk=reused_by_pk).guid
                except Addon.DoesNotExist:
                    log.info(
                        'Addon id [%s] not found so no guid to backfill ' '%s.',
                        reused_by_pk,
                        pks_to_add,
                    )
                    continue
                log.info('Addons %s being added with guid [%s].', pks_to_add, real_guid)
                ReusedGUID.objects.bulk_create(
                    (ReusedGUID(addon_id=pk, guid=real_guid) for pk in pks_to_add),
                    ignore_conflicts=True,
                )
