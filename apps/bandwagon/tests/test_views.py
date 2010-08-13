from django.utils.datastructures import MultiValueDict

from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
import amo.test_utils
from addons.models import Addon
from amo.urlresolvers import reverse
from amo.utils import urlparams
from bandwagon import forms
from bandwagon.models import Collection, CollectionVote, CollectionUser
from users.models import UserProfile


def test_addons_form():
    f = forms.AddonsForm(MultiValueDict({'addon': [''],
                                         'addon_comment': ['comment']}))
    eq_(f.is_valid(), True)


class TestViews(amo.test_utils.ExtraSetup, test_utils.TestCase):
    fixtures = ['users/test_backends', 'bandwagon/test_models',
                'base/addon_3615']

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

    def test_collection_directory_redirects(self):
        base = reverse('collections.list')
        tests = [
            ('/collections/editors_picks', 301,
             urlparams(base, sort='featured')),
            ('/collections/popular/', 301,
             urlparams(base, sort='popular')),
            # These don't work without a login.
            ('/collections/mine', 301, base),
            ('/collections/favorites/', 301, base),
        ]
        for test in tests:
            self.check_response(*test)

    def test_collection_directory_redirects_with_login(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')

        tests = [
            ('/collections/mine', 301,
             reverse('collections.user', args=['jbalogh'])),
            ('/collections/favorites/', 301,
             reverse('collections.detail', args=['jbalogh', 'favorites'])),
        ]
        for test in tests:
            self.check_response(*test)

    def test_unreviewed_addon(self):
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        addon = Addon.objects.all()[0]
        addon.status = amo.STATUS_UNREVIEWED
        c = u.favorites_collection()
        c.add_addon(addon)

        self.client.login(username='jbalogh@mozilla.com', password='foo')
        response = self.client.get(c.get_url_path())
        eq_(list(response.context['addons'].object_list), [addon])


class TestPrivacy(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        # The favorites collection is created automatically.
        self.url = reverse('collections.detail', args=['jbalogh', 'favorites'])
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        eq_(self.client.get(self.url).status_code, 200)
        self.client.logout()
        self.c = Collection.objects.get(slug='favorites',
                                        author__nickname='jbalogh')

    def test_owner(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        eq_(self.client.get(self.url).status_code, 200)

    def test_private(self):
        self.client.logout()
        self.client.login(username='fligtar@gmail.com', password='foo')
        eq_(self.client.get(self.url).status_code, 403)

    def test_public(self):
        # Make it public, others can see it.
        eq_(self.client.get(self.url).status_code, 403)
        self.c.listed = True
        self.c.save()
        eq_(self.client.get(self.url).status_code, 200)

    def test_publisher(self):
        self.c.listed = False
        self.c.save()
        eq_(self.client.get(self.url).status_code, 403)
        u = UserProfile.objects.get(email='fligtar@gmail.com')
        CollectionUser.objects.create(collection=self.c, user=u)
        self.client.login(username='fligtar@gmail.com', password='foo')
        eq_(self.client.get(self.url).status_code, 200)


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


class TestCRUD(test_utils.TestCase):
    """Test the collection form."""
    fixtures = ('base/apps',
                'base/users',
                'base/addon_3615',
                'base/collections',
               )

    def setUp(self):
        login = self.client.login(username='admin@mozilla.com',
                                  password='password')
        assert login, "Couldn't log in."
        self.add_url = reverse('collections.add')
        self.data = {
                'addon': 3615,
                'addon_comment': "fff",
                'name': "flagtir's ye ole favorites",
                'slug': "pornstar",
                'description': '',
                'listed': 'True',
                }

    def login_regular(self):
        login = self.client.login(username='regular@mozilla.com',
                                  password='password')

        assert login, "Couldn't login as regular user."

    def create_collection(self):
        return self.client.post(self.add_url, self.data, follow=True)

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

    def test_reassign(self):
        """
        When reassigning an addon make sure we don't give it a duplicate slug.
        """

        # Create an addon by user 1.
        self.create_collection()

        # Create an addon by user 2 with matching slug.
        self.login_regular()
        self.client.post(self.add_url, self.data, follow=True)
        # Add user1 to user 2.

        # Make user1 owner of user2s addon.
        url = reverse('collections.edit_contributors',
                      args=['regularuser', 'pornstar'])
        self.client.post(url, {'contributor': 4043307, 'new_owner': 4043307},
                         follow=True)
        # verify that user1's addon is slug + '-'
        c = Collection.objects.get(slug='pornstar-')
        eq_(c.author_id, 4043307)

    def test_edit(self):
        self.create_collection()
        url = reverse('collections.edit', args=['admin', 'pornstar'])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)

    def test_edit_post(self):
        """Test edit of collection."""
        self.client.post(self.add_url, self.data, follow=True)
        url = reverse('collections.edit',
                      args=['admin', 'pornstar'])

        self.client.post(url, {'name': 'HALP', 'slug': 'halp', 'listed': True},
                         follow=True)
        c = Collection.objects.get(slug='halp')
        eq_(unicode(c.name), 'HALP')

    def test_forbidden_edit(self):
        r = self.client.post(self.add_url, self.data, follow=True)
        self.login_regular()
        url_args = ['admin', 'pornstar']

        url = reverse('collections.edit', args=url_args)
        r = self.client.get(url)
        eq_(r.status_code, 403)

        url = reverse('collections.edit_addons', args=url_args)
        r = self.client.get(url)
        eq_(r.status_code, 403)

        url = reverse('collections.edit_contributors', args=url_args)
        r = self.client.get(url)
        eq_(r.status_code, 403)

    def test_edit_addons(self):
        self.create_collection()
        url = reverse('collections.edit_addons', args=['admin', 'pornstar'])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)

    def test_edit_addons_post(self):
        self.create_collection()
        url = reverse('collections.edit_addons',
                      args=['admin', 'pornstar'])
        self.client.post(url, {'addon': 3615}, follow=True)
        addon = Collection.objects.filter(slug='pornstar')[0].addons.all()[0]
        eq_(addon.id, 3615)

    def test_delete(self):
        self.create_collection()
        eq_(len(Collection.objects.filter(slug='pornstar')), 1)

        url = reverse('collections.delete',
                      args=['admin', 'pornstar'])
        self.client.post(url, dict(sure=0))
        eq_(len(Collection.objects.filter(slug='pornstar')), 1)
        self.client.post(url, dict(sure='1'))
        eq_(len(Collection.objects.filter(slug='pornstar')), 0)

    @patch('access.acl.action_allowed')
    def test_admin(self, f):
        self.create_collection()
        url = reverse('collections.edit_contributors',
                      args=['admin', 'pornstar'])
        r = self.client.get(url, follow=True)
        doc = pq(r.content)
        eq_(doc('form h3').text(), 'Admin Settings')

        r = self.client.post(url, dict(application=1, type=0), follow=True)
        eq_(r.status_code, 200)

    def test_delete_link(self):
         # Create an addon by user 1.
        self.create_collection()

        url = reverse('collections.edit_contributors',
                      args=['admin', 'pornstar'])
        self.client.post(url, {'contributor': 999}, follow=True)
        url = reverse('collections.edit_addons', args=['admin', 'pornstar'])

        r = self.client.get(url)
        doc = pq(r.content)
        eq_(len(doc('#collection-delete-link')), 1)

        self.login_regular()
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(len(doc('#collection-delete-link')), 0)


    def test_form_uneditable_slug(self):
        """
        Editing a mobile or favorite collection should have an uneditable slug.
        """
        u = UserProfile.objects.get(nickname='admin')
        Collection(author=u, slug='mobile', type=amo.COLLECTION_MOBILE).save()
        url = reverse('collections.edit', args=['admin', 'mobile'])
        r = self.client.get(url, follow=True)
        doc = pq(r.content)
        eq_(len(doc('#id_slug')), 0)

    def test_form_uneditable_slug_submit(self):
        """
        Ignore the slug request change, if some jackass thinks he can change
        it.
        """
        u = UserProfile.objects.get(nickname='admin')
        Collection(author=u, slug='mobile', type=amo.COLLECTION_MOBILE).save()
        url = reverse('collections.edit', args=['admin', 'mobile'])
        r = self.client.post(url,
                             {'name': 'HALP', 'slug': 'halp', 'listed': True},
                             follow=True)

        assert not Collection.objects.filter(slug='halp', author=u)
        assert Collection.objects.filter(slug='mobile', author=u)

class TestChangeAddon(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.add = reverse('collections.alter',
                           args=['jbalogh', 'mobile', 'add'])
        self.remove = reverse('collections.alter',
                              args=['jbalogh', 'mobile', 'remove'])
        self.flig = Collection.objects.create(author_id=9945, slug='xxx')
        self.flig_add = reverse('collections.alter',
                                args=['fligtar', 'xxx', 'add'])
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def check_redirect(self, request):
        url = '%s?addon_id=%s' % (reverse('collections.ajax_list'),
                                  self.addon.id)
        self.assertRedirects(request, url)

    def test_login_required(self):
        self.client.logout()
        r = self.client.post(self.add)
        eq_(r.status_code, 302)
        self.assert_(reverse('users.login') in r['Location'], r['Location'])

    def test_post_required(self):
        r = self.client.get(self.add)
        eq_(r.status_code, 405)

    def test_ownership(self):
        r = self.client.post(self.flig_add)
        eq_(r.status_code, 403)

    def test_publisher(self):
        CollectionUser.objects.create(user_id=4043307, collection=self.flig)
        r = self.client.post(self.flig_add, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)

    def test_no_addon(self):
        r = self.client.post(self.add)
        eq_(r.status_code, 400)

    def test_add_success(self):
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)
        c = Collection.objects.get(author__nickname='jbalogh', slug='mobile')
        self.assert_(self.addon in c.addons.all())
        eq_(c.addons.count(), 1)

    def test_add_existing(self):
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)
        c = Collection.objects.get(author__nickname='jbalogh', slug='mobile')
        self.assert_(self.addon in c.addons.all())
        eq_(c.addons.count(), 1)

    def test_remove_success(self):
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)

        r = self.client.post(self.remove, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)

        c = Collection.objects.get(author__nickname='jbalogh', slug='mobile')
        eq_(c.addons.count(), 0)

    def test_remove_nonexistent(self):
        r = self.client.post(self.remove, {'addon_id': self.addon.id},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.check_redirect(r)
        c = Collection.objects.get(author__nickname='jbalogh', slug='mobile')
        eq_(c.addons.count(), 0)

    def test_no_ajax_response(self):
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             follow=True)
        self.assertRedirects(r, reverse('collections.detail',
                                        args=['jbalogh', 'mobile']))


