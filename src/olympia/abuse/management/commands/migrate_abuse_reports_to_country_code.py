from django.core.management.base import BaseCommand, CommandError

import olympia.core.logger
from olympia.abuse.models import AbuseReport


log = olympia.core.logger.getLogger('z.abuse')


class Command(BaseCommand):
    def setup_check(self):
        value = AbuseReport.lookup_country_code_from_ip('1.1.1.1')

        if not value:
            raise CommandError('GeoIP lookups does not appear to be working.')

    def handle(self, *args, **kwargs):
        self.setup_check()

        qs = AbuseReport.objects.only('ip_address', 'country_code').filter(
            ip_address__isnull=False, country_code__isnull=True)
        for report in qs:
            log.info('Looking up country_code for abuse report %d', report.pk)
            value = AbuseReport.lookup_country_code_from_ip(report.ip_address)
            report.update(country_code=value)
