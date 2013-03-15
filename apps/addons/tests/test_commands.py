from nose import SkipTest
from nose.tools import eq_

from addons.management.commands.import_personas import Command
from addons.models import Addon, Persona
import amo
import amo.tests
from users.models import UserProfile


# This is not a full set of tests, just some smoke tests.
class MockCommand(Command):
    # Just overrides all the stuff that talks to the persona db.
    def __init__(self):
        self.logs = []
        self.designers = {}
        self.users = [['some_username', 'some_display', 'algo$salt$pass',
                       'foo@bar.com', '..', '..', '..', '\x92']]
        self.favourites = []

    def connect(self, *args, **kw):
        pass

    def log(self, msg):
        self.logs.append(msg)

    def get_designers(self, *args):
        return self.designers

    def count_users(self):
        return len(self.users)

    def get_users(self, *args):
        return self.users

    def get_favourites(self, *args):
        return self.favourites


class TestCommand(amo.tests.TestCase):

    def setUp(self):
        raise SkipTest, 'We are doing raw SQL queries now'
        self.cmd = MockCommand()

    def test_users(self):
        self.cmd.handle(commit='yes', users='yes')
        eq_(UserProfile.objects.count(), 1)
        user = UserProfile.objects.get(email='foo@bar.com')
        eq_(user.password, 'algo+base64$salt$pass')
        eq_(str(user.bio), '\xc2\x92')
        assert user.user  # check a Django user got created
        eq_(user.favorites_collection().addons.count(), 0)

    def test_existing(self):
        UserProfile.objects.create(email='foo@bar.com')
        self.cmd.handle(commit='yes', users='yes')
        assert ' Ignoring existing user: foo@bar.com' in self.cmd.logs
        eq_(UserProfile.objects.count(), 1)

    def test_favorites(self):
        addon = Addon.objects.create(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=3, addon=addon)
        UserProfile.objects.create(email='foo@bar.com')
        self.cmd.handle(commit='yes', users='yes')
        self.cmd.favourites = [[3], [4]]
        self.cmd.handle(commit='yes', favorites='yes')
        user = UserProfile.objects.get(email='foo@bar.com')
        eq_(user.favorites_collection().addons.count(), 1)

    def test_designers(self):
        addon = Addon.objects.create(type=amo.ADDON_PERSONA)
        Persona.objects.create(persona_id=3, addon=addon)
        self.cmd.designers = [[3], [4]]
        self.cmd.handle(commit='yes', users='yes')
        msg = ' Skipping unknown persona (4) for user (some_username)'
        assert msg in self.cmd.logs
        user = UserProfile.objects.get(email='foo@bar.com')
        eq_([user], list(addon.listed_authors))
