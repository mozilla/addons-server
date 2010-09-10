from django import test

from commonware.middleware import HidePasswordOnException
from nose.tools import eq_
from pyquery import PyQuery as pq
from test_utils import TestCase, RequestFactory

from amo.urlresolvers import reverse
from zadmin.models import Config, _config_cache


def test_no_vary_cookie():
    # We don't break good usage of Vary.
    response = test.Client().get('/')
    eq_(response['Vary'], 'Accept-Language, User-Agent')

    # But we do prevent Vary: Cookie.
    response = test.Client().get('/', follow=True)
    assert 'Vary' not in response


def test_redirect_with_unicode_get():
    response = test.Client().get('/da/firefox/addon/5457?from=/da/firefox/'
            'addon/5457%3Fadvancedsearch%3D1&lang=ja&utm_source=Google+%E3'
            '%83%90%E3%82%BA&utm_medium=twitter&utm_term=Google+%E3%83%90%'
            'E3%82%BA')
    eq_(response.status_code, 301)


def test_trailing_slash_middleware():
    response = test.Client().get(u'/en-US/firefox/about/?xxx=\xc3')
    eq_(response.status_code, 301)
    assert response['Location'].endswith('/en-US/firefox/about?xxx=%C3%83')


class AdminMessageMiddlewareTest(TestCase):
    def test_message(self):
        c = Config()
        c.key = 'site_notice'
        c.value = 'ET Sighted.'
        c.save()

        if ('site_notice',) in _config_cache:
            del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(doc('#site-notice').text(), 'ET Sighted.')

        c.delete()

        del _config_cache[('site_notice',)]

        r = self.client.get(reverse('home'), follow=True)
        doc = pq(r.content)
        eq_(len(doc('#site-notice')), 0)


def test_hide_password_middleware():
    request = RequestFactory().post('/', dict(x=1, password=2, password2=2))
    request.POST._mutable = False
    HidePasswordOnException().process_exception(request, Exception())
    eq_(request.POST['x'], '1')
    eq_(request.POST['password'], '******')
    eq_(request.POST['password2'], '******')
