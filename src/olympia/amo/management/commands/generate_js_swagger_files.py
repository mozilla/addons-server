from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.http import HttpRequest
from django.utils.encoding import force_str

from olympia.api.views import serve_swagger_ui_js


class Command(BaseCommand):
    help = 'Generate static swagger files'
    requires_system_checks = []  # Can be ran without the database up yet.

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Print verbose output',
        )

    def handle(self, *args, **options):
        request = HttpRequest()
        # Add a script parameter to the request to get the swagger UI JS
        request.GET['script'] = '1'
        request.method = 'GET'
        request.META = {
            'SERVER_NAME': '.mozilla.org',
            'SERVER_PORT': '80',
        }

        self.stdout.write('Generating swagger UI JS...')

        root = Path(settings.STATIC_BUILD_PATH) / 'js' / 'swagger'

        if not root.exists():
            if options['verbose']:
                self.stdout.write(f'Creating directory: {root}')
            root.mkdir(parents=True)

        for version in ('v3', 'v4', 'v5'):
            response = serve_swagger_ui_js(request, version)
            if response.status_code != 200:
                raise CommandError(f'Unexpected status code: {response.status_code}')
            response.render()
            filename = root / f'{version}.js'
            content = force_str(response.content)
            filename.write_text(content)
            if options['verbose']:
                self.stdout.write(f'Swagger UI JS file: {filename}')
                self.stdout.write(content)

        self.stdout.write('Swagger UI JS generated successfully.')
