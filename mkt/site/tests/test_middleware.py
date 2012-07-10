from django.conf import settings

import mock
from nose.tools import eq_

import amo.tests


class TestMiddleware(amo.tests.TestCase):

    def test_no_vary_cookie(self):
        # What is expected to `Vary`.
        r = self.client.get('/privacy-policy')
        eq_(r['Vary'],
            'Accept-Language, X-Requested-With, X-Mobile, User-Agent')

        # But we do prevent `Vary: Cookie`.
        r = self.client.get('/privacy-policy', follow=True)
        eq_(r['Vary'], 'X-Requested-With, X-Mobile, User-Agent')

    # Patching MIDDLEWARE_CLASSES because other middleware tweaks vary headers.
    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES', [
        'amo.middleware.LocaleAndAppURLMiddleware',
        'amo.middleware.CommonMiddleware',
        'amo.middleware.NoVarySessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware'])
    def test_no_user_agent(self):
        # We've toggled the middleware to not rewrite the application and also
        # not vary headers based on User-Agent.
        self.client.login(username='31337', password='password')
        r = self.client.get('/purchases', follow=True)
        eq_(r.status_code, 200)
        assert 'firefox' not in r.request['PATH_INFO'], (
            'Application should not be in the request URL.')
        assert 'User-Agent' not in r['Vary'], (
            'User-Agent should not be in the "Vary" header.')
