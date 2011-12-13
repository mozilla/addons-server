from django.conf import settings
from django.core.management.base import NoArgsCommand
from users.models import UserProfile


class Command(NoArgsCommand):
    requires_model_validation = False
    output_transaction = True

    def handle_noargs(self, **options):

        if not settings.PWD_ALGORITHM == 'bcrypt':
            return

        for user in UserProfile.objects.all():
            user.upgrade_password_to(algorithm='bcrypt')
