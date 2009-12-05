from django.test import TestCase



class MiddlewareTest(TestCase):
    """
    Tests that the locale and app redirection work propperly
    """

    def test_redirection(self):
        redirections = {
        '/': '/en-US/firefox/',
        '/en-US': '/en-US/firefox',
        '/sda/dasdas': '/en-US/firefox/sda/dasdas',
        '/sda/dasdas/': '/en-US/firefox/sda/dasdas/',
        '/sda/firefox/foo': '/en-US/firefox/foo',
        '/firefox': '/en-US/firefox',
        '/admin': '/en-US/admin',
        }
        for path, redirection in redirections.items():
            response = self.client.get(path)
            location = response['Location'].replace('http://testserver', '',
                1)

            self.assertEqual(location, redirection,
                "Expected %s to redirect to %s, but it went to %s" %
                (path, redirection, location))
