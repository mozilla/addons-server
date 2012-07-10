from django.conf import settings

import mock
from nose.tools import eq_
from test_utils import RequestFactory

import amo.tests
from amo.decorators import no_login_required
from amo.middleware import LoginRequiredMiddleware


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


def normal_view(request):
    return ''


@no_login_required
def allowed_view(request):
    return normal_view(request)


class TestLoginRequiredMiddleware(amo.tests.TestCase):

    def process(self, authenticated, view=None, url='/', lang='en-US',
                app='firefox'):
        if not view:
            view = normal_view
        request = RequestFactory().get(url, HTTP_X_PJAX=True)
        request.user = mock.Mock()
        request.APP = amo.APPS[app]
        request.LANG = lang
        request.user.is_authenticated.return_value = authenticated
        return LoginRequiredMiddleware().process_view(request, view, [], {})

    def test_middleware(self):
        # Middleware returns None if it doesn't need to redirect the user.
        assert not self.process(True)
        eq_(self.process(False).status_code, 302)

    def test_middleware_marketplace_home_skip_redirect(self):
        # Middleware returns None if it doesn't need to redirect the user.
        assert not self.process(True)
        res = self.process(False)
        eq_(res.status_code, 302)
        assert '?to=' not in res._headers['location'][1], (
            '/ should not redirect to /?to=/')

    def test_middleware_marketplace_login_skip_redirect(self):
        assert not self.process(True, url=settings.LOGIN_URL)
        res = self.process(False, url=settings.LOGIN_URL)
        eq_(res.status_code, 302)
        assert '?to=' not in res._headers['location'][1], (
            '/users/login should not redirect to /?to=/users/login')

    def test_middleware_marketplace_home_do_redirect(self):
        assert not self.process(True, url='/developers')
        res = self.process(False, url='/developers')
        eq_(res.status_code, 302)
        assert res._headers['location'][1].endswith('?to=%2Fdevelopers'), (
            '/developers should redirect to /?to=/developers')
