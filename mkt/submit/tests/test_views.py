from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
import mkt
from users.models import UserProfile


class TestSubmit(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='password')

    def get_user(self):
        return UserProfile.objects.get(username='regularuser')

    def _test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def _test_progress_display(self, completed, current):
        """Test that the correct steps are highlighted."""
        r = self.client.get(self.url)
        progress = pq(r.content)('#submission-progress')

        # Check the completed steps.
        completed_found = progress.find('.completed')
        for idx, step in enumerate(completed):
            li = completed_found.eq(idx)
            eq_(li.text(), unicode(mkt.APP_STEPS_TITLE[step]))

        # Check the current step.
        eq_(progress.find('.current').text(),
            unicode(mkt.APP_STEPS_TITLE[current]))


class TestTerms(TestSubmit):
    fixtures = ['base/users']

    def setUp(self):
        super(TestTerms, self).setUp()
        self.url = reverse('submit.app.terms')

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def test_jump_to_step(self):
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assertRedirects(r, self.url)

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#submit-terms').length, 1)

    def test_progress_display(self):
        self._test_progress_display([], 'terms')

    def test_agree(self):
        r = self.client.post(self.url, {'read_dev_agreement': True})
        self.assertRedirects(r, reverse('submit.app.manifest'))
        eq_(self.get_user().read_dev_agreement, True)

    def test_disagree(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 200)
        eq_(self.user.read_dev_agreement, False)


class TestManifest(TestSubmit):
    fixtures = ['base/users']

    def setUp(self):
        super(TestManifest, self).setUp()
        self.url = reverse('submit.app.manifest')

    def _step(self):
        self.user.update(read_dev_agreement=True)

    def test_anonymous(self):
        self._test_anonymous()

    def test_cannot_skip_prior_step(self):
        r = self.client.get(self.url, follow=True)
        # And we start back at one...
        self.assertRedirects(r, reverse('submit.app.terms'))

    def test_jump_to_step(self):
        # I already read the Terms.
        self._step()
        # So jump me to the Manifest step.
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assertRedirects(r, reverse('submit.app.manifest'))

    def test_page(self):
        self._step()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#submit-manifest').length, 1)

    def test_progress_display(self):
        self._step()
        self._test_progress_display(['terms'], 'manifest')
