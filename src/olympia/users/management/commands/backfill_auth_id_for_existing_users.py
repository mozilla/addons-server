from django.core.management.base import BaseCommand

from olympia.amo.utils import chunked
from olympia.users.models import UserProfile
from olympia.users.tasks import generate_auth_id_for_users


class Command(BaseCommand):
    def handle(self, *args, **options):
        pks = (UserProfile.objects.filter(auth_id=None)
                          .values_list('pk', flat=True).order_by('pk'))
        for chunk in chunked(pks, 1000):
            generate_auth_id_for_users.delay(chunk)
