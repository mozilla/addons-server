from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users')


class Command(BaseCommand):
    help = 'Clear last_login_ip on users banned more than a year ago'

    def handle(self, *args, **options):
        six_months_ago = datetime.now() - timedelta(days=183)
        qs = UserProfile.objects.filter(
            deleted=True,
            modified__lt=six_months_ago).exclude(last_login_ip='')
        log.info('Clearing last_login_ip for %d users', qs.count())
        for user in qs:
            user.update(last_login_ip='', _signal=False)
