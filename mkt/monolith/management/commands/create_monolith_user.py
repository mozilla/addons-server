from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand


from mkt.site.management.commands.add_test_users import create_user


class Command(BaseCommand):
    help = """Create an user with access to the monolith API"""
    option_list = BaseCommand.option_list + (
        make_option('--overwrite',
                    action='store_true',
                    dest='overwrite',
                    default=False,
                    help='Overwrite the user if it already exist'),)

    def handle(self, *args, **kw):
        create_user('monolith@mozilla.com',
                    delete_user=kw['overwrite'],
                    password=settings.MONOLITH_PASSWORD,
                    permissions=('Monolith:API', ))
