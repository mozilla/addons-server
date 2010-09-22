from django.core.management.base import BaseCommand

from celery.messaging import establish_connection


class Command(BaseCommand):
    help = "Make sure everyone has an auth.User model"

    def handle(self, *args, **kw):
        from amo.utils import chunked
        from users.models import UserProfile
        from users.tasks import make_django_user

        ids = list((UserProfile.objects.filter(user=None, email__isnull=False)
                   .values_list('id', flat=True)))
        print 'Spawning tasks to convert %s users.' % len(ids)

        with establish_connection() as conn:
            for chunk in chunked(ids, 100):
                make_django_user.apply_async(args=chunk, connection=conn)
