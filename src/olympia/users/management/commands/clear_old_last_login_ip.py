from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users')


class Command(BaseCommand):
    help = 'Clear last_login_ip on users banned more than a year ago'

    def handle(self, *args, **options):
        a_year_ago = datetime.now() - timedelta(days=365)
        qs = UserProfile.objects.filter(
            deleted=True, banned__lt=a_year_ago).exclude(last_login_ip='')
        log.info('Clearing last_login_ip for %d users', qs.count())
        for user in qs:
            user.update(last_login_ip='', _signal=False)
