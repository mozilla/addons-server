from django import test

from nose.tools import eq_
import test_utils

from amo import urlresolvers
from amo.middleware import LocaleAndAppURLMiddleware


class MiddlewareTest(test.TestCase):
    """
    Tests that the locale and app redirection work propperly
    """

    def setUp(self):
        self.rf = test_utils.RequestFactory()
        self.middleware = LocaleAndAppURLMiddleware()

    def test_redirection(self):
        redirections = {
            '/': '/en-US/firefox/',
            '/en-US': '/en-US/firefox/',
            '/firefox': '/en-US/firefox/',

            # Make sure we don't mess with trailing slashes.
            '/addon/1/': '/en-US/firefox/addon/1/',
            '/addon/1': '/en-US/firefox/addon/1',

            # Check an invalid locale.
            '/sda/firefox/addon/1': '/en-US/firefox/addon/1',

            # /admin doesn't get an app.
            '/developers': '/en-US/developers',
        }

        for path, location in redirections.items():
            response = self.middleware.process_request(self.rf.get(path))
            eq_(response.status_code, 301)
            eq_(response['Location'], location)

    def test_no_redirect(self):
        # /services doesn't get an app or locale.
        response = self.middleware.process_request(self.rf.get('/services'))
        assert response is None

    def test_vary_locale(self):
        response = self.middleware.process_request(self.rf.get('/'))
        eq_(response['Vary'], 'Accept-Language')

        response = self.middleware.process_request(self.rf.get('/en-US'))
        assert 'Vary' not in response

    def test_no_redirect_with_script(self):
        request = self.rf.get('/services', SCRIPT_NAME='/oremj')
        response = self.middleware.process_request(request)
        assert response is None


class TestPrefixer:

    def setup(self):
        urlresolvers._prefixes.clear()

    def test_split_path(self):

        def split_eq(url, locale, app, path):
            rf = test_utils.RequestFactory()
            prefixer = urlresolvers.Prefixer(rf.get(url))
            actual = (prefixer.locale, prefixer.app, prefixer.shortened_path)
            eq_(actual, (locale, app, path))

        split_eq('/', '', '', '')
        split_eq('/en-US', 'en-US', '', '')
        split_eq('/en-US/firefox', 'en-US', 'firefox', '')
        split_eq('/en-US/firefox/', 'en-US', 'firefox', '')
        split_eq('/en-US/firefox/foo', 'en-US', 'firefox', 'foo')
        split_eq('/en-US/firefox/foo/', 'en-US', 'firefox', 'foo/')
        split_eq('/en-US/foo', 'en-US', '', 'foo')
        split_eq('/en-US/foo/', 'en-US', '', 'foo/')
        split_eq('/bad/firefox/foo', '', 'firefox', 'foo')
        split_eq('/bad/firefox/foo/', '', 'firefox', 'foo/')
        split_eq('/firefox/foo', '', 'firefox', 'foo')
        split_eq('/firefox/foo/', '', 'firefox', 'foo/')
        split_eq('/foo', '', '', 'foo')
        split_eq('/foo/', '', '', 'foo/')

    def test_fix(self):
        rf = test_utils.RequestFactory()
        prefixer = urlresolvers.Prefixer(rf.get('/'))

        eq_(prefixer.fix('/'), '/en-US/firefox/')
        eq_(prefixer.fix('/foo'), '/en-US/firefox/foo')
        eq_(prefixer.fix('/foo/'), '/en-US/firefox/foo/')
        eq_(prefixer.fix('/admin'), '/en-US/admin')
        eq_(prefixer.fix('/admin/'), '/en-US/admin/')

        prefixer.locale = 'de'
        prefixer.app = 'thunderbird'

        eq_(prefixer.fix('/'), '/de/thunderbird/')
        eq_(prefixer.fix('/foo'), '/de/thunderbird/foo')
        eq_(prefixer.fix('/foo/'), '/de/thunderbird/foo/')
        eq_(prefixer.fix('/admin'), '/de/admin')
        eq_(prefixer.fix('/admin/'), '/de/admin/')

    def test_reverse(self):
        # Make sure it works outside the request.
        eq_(urlresolvers.reverse('home'), '/')

        # With a request, locale and app prefixes work.
        client = test.Client()
        client.get('/')
        eq_(urlresolvers.reverse('home'), '/en-US/firefox/')

    def test_script_name(self):
        rf = test_utils.RequestFactory()
        request = rf.get('/foo', SCRIPT_NAME='/oremj')
        prefixer = urlresolvers.Prefixer(request)
        eq_(prefixer.fix(prefixer.shortened_path), '/oremj/en-US/firefox/foo')
