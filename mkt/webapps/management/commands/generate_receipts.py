from optparse import make_option

from django.core.management.base import BaseCommand, CommandError
import json
import os
import tempfile
import time

import amo
from addons.models import Addon
from users.models import UserProfile
from mkt.webapps.models import Installed


class Command(BaseCommand):
    """
    Used to generate a whole pile of receipts that can be used for
    load testing. The receipts need to be generated because they use
    the receipt key for the particular server.

    This will create users, addons and installed records, so that the
    verify script can be load tested properly.

    These records are placed into a JSON file. Run the delete command
    to clean these out afterwards.
    """
    option_list = BaseCommand.option_list + (
        make_option('--action', action='store', type='string',
                    dest='action', help='Action: create, delete.'),
        make_option('--dir', action='store', type='string',
                    dest='dir', help='Directory to read or write data.'),
        make_option('--number', action='store', type='int', default='10',
            dest='number', help='Number of receipts, default: %default')
    )

    def filename(self, rest):
        return os.path.join(self.dest, rest)

    def handle(self, *args, **options):
        self.dest = options.get('dir')
        action = options.get('action')
        if action not in ['create', 'delete']:
            raise CommandError('Action: create or delete')

        if not self.dest:
            self.dest = tempfile.mkdtemp()
            print '--dir not specified, using: %s' % self.dest

        if not os.path.exists(self.dest):
            print 'Creating output directory, %s' % self.dest
            os.makedirs(self.dest)

        self.number = options.get('number')
        return getattr(self, action)()

    def create(self):
        """
        Creates users, webapps and installed records. Outputs the receipts
        and created records into the supplied directory.
        """
        created = {'users': [], 'webapps': [], 'installed': []}
        number = self.number
        stamp = str(time.time())

        for x in xrange(number):
            name = 'generate-receipt-%s-%s' % (stamp, x)
            user = UserProfile.objects.create(email='%s@mozilla.com' % name,
                                              username=name)
            created['users'].append(user.pk)

        for x in xrange(number):
            name = 'generate-receipt-%s-%s' % (stamp, x)
            addon = Addon.objects.create(name=name,
                                         type=amo.ADDON_WEBAPP,
                                         manifest_url='http://a.com/m.webapp')
            created['webapps'].append(addon.pk)

        for x in xrange(number):
            installed = Installed.objects.create(
                            addon_id=created['webapps'][x],
                            user_id=created['users'][x])
            created['installed'].append(installed.pk)
            filename = self.filename('%s.%s.receipt' %
                                     (created['webapps'][x], x))
            open(filename, 'w').write(installed.receipt)

        open(self.filename('created.json'), 'w').write(json.dumps(created))

    def delete(self):
        """Cleans up once the load testing is run and deletes the records."""
        data = json.loads(open(self.filename('created.json'), 'r').read())
        for obj, model in (['installed', Installed],
                           ['webapps', Addon],
                           ['users', UserProfile]):
            model.objects.filter(pk__in=data[obj]).delete()
