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
