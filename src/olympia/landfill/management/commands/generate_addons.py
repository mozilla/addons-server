from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from olympia.landfill.generators import generate_addons


class Command(BaseCommand):
    """
    Generate example addons for development/testing purpose.

    Addons will have 1 preview image, 2 translations (French and
    Spanish), 5 ratings and might be featured randomly. If you don't
    provide any --owner email address, all created add-ons will have
    'nobody@mozilla.org' as owner. If you don't provide any --app name,
    all created add-ons will have 'firefox' as application.

    Categories from production (Alerts & Updates, Appearance, etc)
    will be created and randomly populated with generated addons.

    Usage:

        python manage.py generate_addons <num_addons>
            [--owner <email>] [--app <application>]

    """

    help = __doc__

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('num', type=int)
        parser.add_argument(
            '--owner',
            action='store',
            dest='email',
            default='nobody@mozilla.org',
            help="Specific owner's email to be created.",
        )
        parser.add_argument(
            '--app',
            action='store',
            dest='app_name',
            default='firefox',
            help="Specific application targeted by add-ons creation.",
        )

    def handle(self, *args, **kwargs):
        if not settings.DEBUG:
            raise CommandError(
                'You can only run this command with your '
                'DEBUG setting set to True.'
            )

        num = int(kwargs.get('num'))
        email = kwargs.get('email')
        app_name = kwargs.get('app_name')

        with translation.override(settings.LANGUAGE_CODE):
            generate_addons(num, email, app_name)
