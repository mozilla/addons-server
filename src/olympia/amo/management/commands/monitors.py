import time

from django.core.management.base import CommandError

import olympia.amo.monitors as monitors

from .. import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Check a set of AMO service monitors.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--services',
            nargs='+',
            help='List of services to check',
        )
        parser.add_argument(
            '--attempts',
            type=int,
            default=5,
            help='Number of attempts to check the services',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Verbose output',
        )

    def handle(self, *args, **options):
        attempts = options.get('attempts')
        services = options.get('services')
        verbose = options.get('verbose')
        self.logger.info(f'services: {services}')

        if not services:
            raise CommandError('No services specified')

        current = 0

        services_to_check = set(services.copy())

        while current < attempts:
            current += 1
            self.logger.info(
                f'Checking services {services_to_check} for the {current} time'
            )
            status_summary = monitors.execute_checks(list(services_to_check), verbose)

            failing_services = {}

            for service, result in status_summary.items():
                if result['state'] is True and service in services_to_check:
                    services_to_check.remove(service)
                else:
                    failing_services[service] = result

            if len(failing_services) > 0:
                self.logger.error('Some services are failing: %s', failing_services)
                sleep_time = round(1.618**current)
                self.logger.info(f'Sleeping for {sleep_time} seconds')
                time.sleep(sleep_time)
            else:
                break

        if len(services_to_check) > 0:
            raise CommandError(f'Some services are failing: {list(services_to_check)}')
        else:
            self.logger.info(f'All services are healthy {services}')
