from nose.tools import eq_
import waffle

from amo.urlresolvers import reverse

from mkt.browse.tests.test_views import BrowseBase


class TestHome(BrowseBase):

    def setUp(self):
        super(TestHome, self).setUp()
        waffle.models.Switch.objects.create(name='unleash-consumer',
                                            active=True)
        self.url = reverse('home')

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'home/home.html')

    def test_featured(self):
        a, b, c = self.setup_featured()
        # Check that these apps are featured.
        eq_(self.get_pks('featured', self.url), [c.id])

    def test_popular(self):
        a, b = self.setup_popular()
        # Check that these apps are shown.
        self._test_popular(self.url, [self.webapp.id, a.id, b.id])
