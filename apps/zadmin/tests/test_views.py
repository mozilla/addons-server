from django import test

import test_utils

from nose.tools import eq_

from amo.urlresolvers import reverse
from addons.models import Addon
from files.models import Approval
from versions.models import Version


class TestFlagged(test_utils.TestCase):
    fixtures = ['zadmin/tests/flagged']

    def setUp(self):
        super(TestFlagged, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def test_get(self):
        url = reverse('zadmin.flagged')
        response = self.client.get(url, follow=True)

        addons = dict((a.id, a) for a in response.context['addons'])
        eq_(len(addons), 3)

        # 1. an addon should have latest version and approval attached
        addon = Addon.objects.get(id=1)
        eq_(addons[1], addon)
        eq_(addons[1].version.id,
            Version.objects.filter(addon=addon).latest().id)
        eq_(addons[1].approval.id,
            Approval.objects.filter(addon=addon).latest().id)

        # 2. missing approval is ok
        addon = Addon.objects.get(id=2)
        eq_(addons[2], addon)
        eq_(addons[2].version.id,
            Version.objects.filter(addon=addon).latest().id)
        eq_(addons[2].approval, None)

        # 3. missing approval is ok
        addon = Addon.objects.get(id=3)
        eq_(addons[3], addon)
        eq_(addons[3].approval.id,
            Approval.objects.filter(addon=addon).latest().id)
        eq_(addons[3].version, None)

    def test_post(self):
        # Do a get first so the query is cached.
        url = reverse('zadmin.flagged')
        self.client.get(url, follow=True)

        response = self.client.post(url, {'addon_id': ['1', '2']}, follow=True)
        self.assertRedirects(response, url)

        assert not Addon.objects.get(id=1).admin_review
        assert not Addon.objects.get(id=2).admin_review

        addons = response.context['addons']
        eq_(len(addons), 1)
        eq_(addons[0], Addon.objects.get(id=3))


def test_settings():
    # Are you there, settings page?
    response = test.Client().get(reverse('zadmin.settings'), follow=True)
    eq_(response.status_code, 200)
