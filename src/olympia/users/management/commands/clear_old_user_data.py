from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import delete_addons
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users')


class Command(BaseCommand):
    help = (
        'Clear user data on addon developers deleted more than 7 years ago, '
        'and non addon-developers after 24 hours')

    def handle(self, *args, **options):
        profile_clear = {
            'last_login_ip': '',
            'email': None,
            'fxa_id': None,
        }
        one_day_ago = datetime.now() - timedelta(days=1)
        seven_years_ago = datetime.now() - timedelta(days=365 * 7)

        seven_year_q = Q(modified__lt=seven_years_ago)
        one_day_q = Q(
            ~Q(**profile_clear),
            addons=None,
            modified__lt=one_day_ago,
            banned=None)
        users = list(
            UserProfile.objects.filter(seven_year_q | one_day_q, deleted=True))

        addons_qs = Addon.unfiltered.filter(
            status__in=(amo.STATUS_DELETED, amo.STATUS_DISABLED),
            authors__in=users)
        addon_ids = list(addons_qs.values_list('id', flat=True))

        log.info('Clearing %s for %d users', profile_clear.keys(), len(users))
        for user in users:
            user.update(**profile_clear, _signal=False)

        if addon_ids:
            delete_addons.delay(addon_ids, with_deleted=True)
