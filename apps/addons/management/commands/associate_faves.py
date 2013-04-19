from optparse import make_option
from time import time

from django.core.management.base import BaseCommand

from addons.models import AddonCollection
from users.models import UserProfile
import amo


class Command(BaseCommand):
    """
    Import from the personas database:
    `host`: the host of the personas database
    `database`: the personas database, eg: personas
    """
    option_list = BaseCommand.option_list + (
        make_option('--from', action='store', dest='from',
                    help='Filename to get users from'),
    )

    def handle(self, *args, **options):
        t_start = time()

        self.connect(**options)

        print "You're running a script to associate favo(u)rites!"

        # Read usernames from a file.
        users_fn = options.get('from')
        with open(users_fn, 'r') as fd:
            self.users = fd.read().strip().replace('\r', '').split('\n')
        self.users = list(set(filter(None, self.users)))

        count = len(self.users)

        print('Found %s users. Grab some tea (loose leaf, none of that bagged '
              'crap) and settle in.' % count)

        changed = 0
        unchanged = 0

        for user_id in self.users:
            try:
                profile = UserProfile.objects.get(id=user_id)
            except UserProfile.DoesNotExist:
                print '[ERROR] User #%s does not exist' % user_id
                continue

            all_ac = (AddonCollection.objects.filter(user_id=user_id)
                      .exclude(collection__type=amo.COLLECTION_FAVORITES))
            if not all_ac.exists():
                print '[OK] User #%s has the correct favourites' % user_id
                continue

            faves_id = profile.favorites_collection.id

            for ac in all_ac:
                if ac.collection_id != faves_id:
                    print('[OK] Changed AddonCollection #%s (from Collection '
                          '#%s to #%s)' % (ac.id, ac.collection_id, faves_id))
                    ac.collection_id = faves_id
                    ac.save()
                    changed += 1
                else:
                    print('[OK] Skipped AddonCollection #%s (from Collection '
                         '#%s)' % (ac.id, faves_id))
                    unchanged += 1

        print '\nDone. Total time: %s seconds' % (time() - t_start)
        print 'Changed: %s. Unchanged: %s.' % (changed, unchanged)
