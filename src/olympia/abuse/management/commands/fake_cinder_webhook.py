import hashlib
import hmac
import os.path
from urllib.parse import urljoin

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils.encoding import force_bytes

import requests


class Command(BaseCommand):
    help = 'Send fake webhook request to local abuse response API like Cinder would.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--payload',
            dest='payload_filename',
            default=os.path.join(settings.ROOT, 'tmp/payload.json'),
            help='Path to filename containing payload (default: %(default)s)',
        )

    def handle(self, *args, **options):
        if settings.ENV != 'local':
            raise CommandError('Only works in local environments')
        try:
            body = open(options['payload_filename'], 'rb').read()
        except FileNotFoundError as exc:
            raise CommandError(
                'Cannot find payload file. Try using --payload=<path>.'
            ) from exc
        signature = hmac.new(
            force_bytes(settings.CINDER_WEBHOOK_TOKEN),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        url = urljoin('http://nginx', reverse('v5:cinder-webhook'))
        response = requests.post(
            url,
            data=body,
            headers={
                'X-Cinder-Signature': signature,
                'Content-Type': 'application/json',
            },
        )
        self.stdout.write(f'{response.status_code}\n')
        self.stdout.write(f'{response.content}\n')
