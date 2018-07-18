from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import translation

from olympia.landfill.generators import generate_themes


class Command(BaseCommand):
    """
    Generate example themes for development/testing purpose.

    Themes will have 1 preview image + header & footer, 2 translations
    (French and Spanish) and 5 ratings. If you don't provide any --owner
    email address, all created add-ons will have 'nobody@mozilla.org'
    as owner.

    Categories from production (Abstract, Causes, Fashion, etc)
    will be created and randomly populated with generated themes.

    Usage:

        python manage.py generate_themes <num_themes> [--owner <email>]

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

    def handle(self, *args, **kwargs):
        if not settings.DEBUG:
            raise CommandError(
                'You can only run this command with your '
                'DEBUG setting set to True.'
            )
        num = int(kwargs.get('num'))
        email = kwargs.get('email')

        with translation.override(settings.LANGUAGE_CODE):
            generate_themes(num, email)
