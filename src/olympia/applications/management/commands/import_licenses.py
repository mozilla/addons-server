from django.core.management.base import BaseCommand

from olympia.constants.licenses import ALL_LICENSES
from olympia.versions.models import License


class Command(BaseCommand):
    help = """Import a the licenses."""

    def handle(self, *args, **options):
        for license in ALL_LICENSES:
            try:
                License.objects.get_or_create(builtin=license.builtin)
            except Exception:
                continue
