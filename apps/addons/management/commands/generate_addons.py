from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from addons.addongenerator import generate_addons


class Command(BaseCommand):
    """
    Generate example addons for development/testing purpose.

    Addons will have 1 preview image, 2 translations (French and
    Spanish), 5 ratings and might be featured randomly. If you don't
    provide any --owner email address, all created addon will have
    'nobody@mozilla.org' as owner.

    Categories from production (Alerts & Updates, Appearance, etc)
    will be created and randomly populated with generated addons.

    Usage:

        python manage.py generate_addons <num_addons> [--owner <email>]

    """

    help = __doc__
    option_list = BaseCommand.option_list + (
        make_option('--owner', action='store', dest='email',
                    help="Specific owner's email to be created."),
    )

    def handle(self, *args, **kwargs):
        num = int(args[0])
        email = kwargs.get('email')
        if settings.DEBUG:
            generate_addons(num, email)
        else:
            raise CommandError('You can only run this command with your '
                               'DEBUG setting set to True.')
