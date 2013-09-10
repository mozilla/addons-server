import amo
import amo.tests

import waffle

from users.models import UserProfile

from mkt.purchase.utils import payments_enabled
from mkt.site.fixtures import fixture

from test_utils import RequestFactory


class TestUtils(amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.req = RequestFactory().get('/')

    def test_settings(self):
        with self.settings(PAYMENT_LIMITED=False):
            assert payments_enabled(self.req)

    def test_not_flag(self):
        with self.settings(PAYMENT_LIMITED=True):
            assert not payments_enabled(self.req)

    def test_flag(self):
        profile = UserProfile.objects.get(pk=2519)

        flag = waffle.models.Flag.objects.create(name='override-app-payments')
        flag.everyone = None
        flag.users.add(profile.user)
        flag.save()

        self.req.user = profile.user
        with self.settings(PAYMENT_LIMITED=True):
            assert payments_enabled(self.req)
