import os

from django.conf import settings
from django.http import QueryDict

from nose.tools import eq_
import test_utils

import amo.test_utils
from amo.urlresolvers import reverse
from bandwagon.models import Collection, CollectionVote


class TestViews(amo.test_utils.ExtraSetup, test_utils.TestCase):
    fixtures = ['bandwagon/test_models.json', 'base/apps']

    def check_response(self, url, code, to=None):
        response = self.client.get(url, follow=True)
        if code == 404:
            eq_(response.status_code, 404)
        elif code in (301, 302):
            self.assertRedirects(response, to, status_code=code)
        else:  # pragma: no cover
            assert code in (301, 302, 404), code

    def test_legacy_redirects(self):
        collection = Collection.objects.get(nickname='wut')
        url = collection.get_url_path()
        tests = [
            ('/collection/wut', 301, url),
            ('/collection/wut/', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4/', 301, url),
            ('/collection/404', 404)]
        for test in tests:
            self.check_response(*test)


class TestVotes(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        args = ['fligtar', 'slug']
        Collection.objects.create(slug='slug', author_id=9945)
        self.c_url = reverse('collections.detail', args=args)
        self.up = reverse('collections.vote', args=args + ['up'])
        self.down = reverse('collections.vote', args=args + ['down'])

    def test_login_required(self):
        self.client.logout()
        r = self.client.post(self.up, follow=True)
        url, _ = r.redirect_chain[-1]
        eq_(r.status_code, 200)
        self.assert_(reverse('users.login') in url)

    def test_post_required(self):
        r = self.client.get(self.up, follow=True)
        self.assertRedirects(r, self.c_url)

    def check(self, upvotes=0, downvotes=0):
        c = Collection.uncached.get(slug='slug', author=9945)
        eq_(c.upvotes, upvotes)
        eq_(c.downvotes, downvotes)
        eq_(CollectionVote.objects.filter(user=4043307, vote=1).count(),
            upvotes)
        eq_(CollectionVote.objects.filter(user=4043307, vote=-1).count(),
            downvotes)
        eq_(CollectionVote.objects.filter(user=4043307).count(),
            upvotes + downvotes)

    def test_upvote(self):
        self.client.post(self.up)
        self.check(upvotes=1)

    def test_downvote(self):
        self.client.post(self.down)
        self.check(downvotes=1)

    def test_down_then_up(self):
        self.client.post(self.down)
        self.check(downvotes=1)
        self.client.post(self.up)
        self.check(upvotes=1)

    def test_up_then_up(self):
        self.client.post(self.up)
        self.check(upvotes=1)
        self.client.post(self.up)
        self.check(upvotes=0)

    def test_normal_response(self):
        r = self.client.post(self.up, follow=True)
        self.assertRedirects(r, self.c_url)

    def test_ajax_response(self):
        r = self.client.post(self.up, follow=True,
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        assert not r.redirect_chain
        eq_(r.status_code, 200)


class TestAdd(test_utils.TestCase):
    """Test the collection form."""
    fixtures = ['base/fixtures']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.add_url = reverse('collections.add')
        self.data = {
                'addon': 3615,
                'addon_comment': "fff",
                'name': "flagtir's ye ole favorites",
                'slug': "pornstar",
                'description': '',
                'listed': 'True'
                }

    def test_showform(self):
        """Shows form if logged in."""
        r = self.client.get(self.add_url)
        eq_(r.status_code, 200)

    def test_submit(self):
        """Test submission of addons."""
        # TODO(davedash): Test file uploads, test multiple addons.
        r = self.client.post(self.add_url, self.data, follow=True)
        eq_(r.request['PATH_INFO'],
            '/en-US/firefox/collections/admin/pornstar/')
        c = Collection.objects.get(slug='pornstar')
        eq_(unicode(c.name), self.data['name'])
        eq_(c.description, None)
        eq_(c.addons.all()[0].id, 3615)

    def test_duplicate_slug(self):
        """Try the same thing twice.  AND FAIL"""
        self.client.post(self.add_url, self.data, follow=True)
        r = self.client.post(self.add_url, self.data, follow=True)
        eq_(r.context['form'].errors['slug'][0],
            'This url is already in use by another collection')
