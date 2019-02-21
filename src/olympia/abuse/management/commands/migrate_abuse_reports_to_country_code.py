from django.core.management.base import BaseCommand, CommandError

from olympia.abuse.models import AbuseReport


class Command(BaseCommand):
    def setup_check(self):
        value = AbuseReport.lookup_country_code_from_ip('1.1.1.1')

        if not value:
            raise CommandError('GeoIP lookups does not appear to be working.')

    def handle(self, *args, **kwargs):
        self.setup_check()

        qs = AbuseReport.objects.filter(ip_address__isnull=False)
        for report in qs:
            value = AbuseReport.lookup_country_code_from_ip(report.ip_address)
            report.update(country_code=value)
