from django.core import mail

from access.models import GroupUser, Group
from addons.models import Addon
import amo.tests
from bandwagon.models import Collection
from reviews.models import Review
from users.models import UserProfile


class TestUserProfile(amo.tests.TestCase):
    fixtures = ('base/addon_3615', 'base/user_2519', 'base/user_4043307',
                'users/test_backends', 'base/apps',)

    def test_restrict(self):
        x = UserProfile.objects.get(email='jbalogh@mozilla.com')
        g, created = Group.objects.get_or_create(rules='Restricted:UGC')
        Collection.objects.create(author=x, name='test collection')
        Review.objects.create(user=x, addon=Addon.objects.get(pk=3615))
        x.restrict()
        assert GroupUser.objects.filter(user=x, group=g).exists()
        assert not Collection.objects.filter(author=x).exists()
        assert not Review.objects.filter(user=x).exists()
        assert 'restricted' in mail.outbox[0].subject

    def test_unrestrict(self):
        x = UserProfile.objects.get(email='jbalogh@mozilla.com')
        g, _ = Group.objects.get_or_create(rules='Restricted:UGC')
        GroupUser.objects.create(group=g, user=x)
        x.unrestrict()
        assert not GroupUser.objects.filter(user=x, group=g).exists()


