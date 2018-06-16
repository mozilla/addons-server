# -*- coding: utf-8 -*-
import json

import django.test

from django.core.cache import cache
from django.forms import ValidationError
from django.utils.datastructures import MultiValueDict
from django.conf import settings

import pytest

from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia import amo, core
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, collection_factory, user_factory)
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.amo.utils import urlparams
from olympia.bandwagon import forms
from olympia.bandwagon.models import (
    Collection, CollectionAddon, CollectionUser, CollectionVote,
    CollectionWatcher)
from olympia.bandwagon.views import CollectionFilter
from olympia.browse.tests import TestFeeds
from olympia.users.models import UserProfile


pytestmark = pytest.mark.django_db


def test_addons_form():
    f = forms.AddonsForm(MultiValueDict({'addon': [''],
                                         'addon_comment': ['comment']}))
    assert f.is_valid()


def test_collections_form_bad_slug():
    f = forms.CollectionForm(dict(slug=' ', listed=True, name='  '))
    assert 'slug' in f.errors
    assert 'name' in f.errors


def test_collections_form_long_description():
    f = forms.CollectionForm(dict(description='&*' * 200))
    assert 'description' in f.errors


def test_collections_form_unicode_slug():
    u = Mock()
    u.collections.filter.return_value.count.return_value = False
    f = forms.CollectionForm(dict(slug=u'Ελλην', listed=True, name='  '),
                             initial=dict(author=u))
    assert 'name' in f.errors
    assert 'slug' not in f.errors


class TestViews(TestCase):
    fixtures = ['users/test_backends', 'bandwagon/test_models',
                'base/addon_3615']

    def check_response(self, url, code, to=None):
        response = self.client.get(url, follow=True)
        if code == 404:
            assert response.status_code == 404
        elif code in (301, 302):
            self.assert3xx(response, to, status_code=code)
        else:  # pragma: no cover
            assert code in (301, 302, 404), code

    def test_legacy_redirects(self):
        collection = Collection.objects.get(nickname='wut')
        url = collection.get_url_path()
        tests = [
            ('/collection/wut?x=y', 301, url + '?x=y'),
            ('/collection/wut/', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4', 301, url),
            ('/collection/f94d08c7-794d-3ce4-4634-99caa09f9ef4/', 301, url),
            ('/collections/view/f94d08c7-794d-3ce4-4634-99caa09f9ef4', 301,
             url),
            ('/collections/view/wut/', 301, url),
            ('/collection/404', 404)]
        for test in tests:
            self.check_response(*test)

    def test_legacy_redirects_edit(self):
        self.client.login(email='jbalogh@mozilla.com')
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        uuid = u.favorites_collection().uuid
        self.check_response('/collections/edit/%s' % uuid, 301,
                            u.favorites_collection().edit_url())

    def test_collection_directory_redirects(self):
        base = reverse('collections.list')
        tests = [
            ('/collections/editors_picks', 301,
             urlparams(base, sort='featured')),
            ('/collections/popular/', 301,
             urlparams(base, sort='popular')),
            # These don't work without a login.
            ('/collections/favorites/', 301, base),
        ]
        for test in tests:
            self.check_response(*test)

    def test_collection_directory_redirects_with_login(self):
        self.client.login(email='jbalogh@mozilla.com')

        self.check_response('/collections/favorites/', 301,
                            reverse('collections.following'))

    def test_unlisted_collection_login_redirect(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')

        urls = (
            '/en-US/firefox/collections/mine/',
            '/en-US/firefox/collections/mine/favorites/',
            user.favorites_collection().get_url_path(),
        )
        for url in urls:
            self.assertLoginRedirects(self.client.get(url), url)

    def test_unreviewed_addon(self):
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        addon = Addon.objects.all()[0]
        addon.status = amo.STATUS_NOMINATED
        c = u.favorites_collection()
        core.set_user(u)
        c.add_addon(addon)

        self.client.login(email='jbalogh@mozilla.com')
        response = self.client.get(c.get_url_path())
        assert list(response.context['addons'].object_list) == [addon]

    def test_mine(self):
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        addon = addon = Addon.objects.all()[0]
        c = u.favorites_collection()
        core.set_user(u)
        c.add_addon(addon)

        assert self.client.login(email='jbalogh@mozilla.com')

        # My Collections.
        response = self.client.get('/en-US/firefox/collections/mine/')
        assert response.context['author'] == (
            UserProfile.objects.get(email='jbalogh@mozilla.com'))

        # My Favorites.
        response = self.client.get(reverse('collections.detail',
                                           args=['mine', 'favorites']))
        assert response.status_code == 200
        assert list(response.context['addons'].object_list) == [addon]

    def test_not_mine(self):
        self.client.logout()
        r = self.client.get(reverse('collections.user', args=['jbalogh']))
        assert r.context['page'] == 'user'
        assert '#p-mine' not in pq(r.content)('style').text(), (
            "'Collections I've Made' sidebar link shouldn't be highlighted.")

    def test_description_no_link_no_markup(self):
        c = Collection.objects.get(slug='wut-slug')
        c.description = ('<a href="http://example.com">example.com</a> '
                         'http://example.com <b>foo</b> some text')
        c.save()

        assert self.client.login(email='jbalogh@mozilla.com')
        response = self.client.get('/en-US/firefox/collections/mine/')
        # All markup is escaped, all links are stripped.
        self.assertContains(response, '&lt;b&gt;foo&lt;/b&gt; some text')

    def test_delete_icon(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        collection = user.favorites_collection()
        edit_url = collection.edit_url()

        # User not logged in: redirect to login page.
        res = self.client.post(collection.delete_icon_url())
        assert res.status_code == 302
        assert res.url != edit_url

        self.client.login(email='jbalogh@mozilla.com')

        res = self.client.post(collection.delete_icon_url())
        assert res.status_code == 302
        assert res.url == 'http://testserver%s' % edit_url

    def test_delete_icon_csrf_protected(self):
        """The delete icon view only accepts POSTs and is csrf protected."""
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        collection = user.favorites_collection()
        client = django.test.Client(enforce_csrf_checks=True)

        client.login(email='jbalogh@mozilla.com')

        res = client.get(collection.delete_icon_url())
        assert res.status_code == 405  # Only POSTs are allowed.

        res = client.post(collection.delete_icon_url())
        assert res.status_code == 403  # The view is csrf protected.

    def test_no_xss_in_collection_page(self):
        coll = Collection.objects.get(slug='wut-slug')
        name = '"><script>alert(/XSS/);</script>'
        name_escaped = '&#34;&gt;&lt;script&gt;alert(/XSS/);&lt;/script&gt;'
        coll.name = name
        coll.save()
        resp = self.client.get(coll.get_url_path())
        assert name not in resp.content
        assert name_escaped in resp.content


class TestPrivacy(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(TestPrivacy, self).setUp()
        # The favorites collection is created automatically.
        self.url = reverse('collections.detail', args=['jbalogh', 'favorites'])
        self.client.login(email='jbalogh@mozilla.com')
        assert self.client.get(self.url).status_code == 200
        self.client.logout()
        self.c = Collection.objects.get(slug='favorites',
                                        author__username='jbalogh')

    def test_owner(self):
        self.client.login(email='jbalogh@mozilla.com')
        r = self.client.get(self.url)
        assert r.status_code == 200
        # TODO(cvan): Uncomment when bug 719512 gets fixed.
        # assert pq(r.content)('.meta .view-stats').length == 1, (
        #    'Add-on authors should be able to view stats')

    def test_private(self):
        self.client.logout()
        self.client.login(email='fligtar@gmail.com')
        assert self.client.get(self.url).status_code == 403

    def test_public(self):
        # Make it public, others can see it.
        self.assertLoginRedirects(self.client.get(self.url), self.url)
        self.c.listed = True
        self.c.save()
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert pq(r.content)('.meta .view-stats').length == 0, (
            'Only add-on authors can view stats')

    def test_publisher(self):
        self.c.listed = False
        self.c.save()
        self.assertLoginRedirects(self.client.get(self.url), self.url)
        u = UserProfile.objects.get(email='fligtar@gmail.com')
        CollectionUser.objects.create(collection=self.c, user=u)
        self.client.login(email='fligtar@gmail.com')
        r = self.client.get(self.url)
        assert r.status_code == 200
        # TODO(cvan): Uncomment when bug 719512 gets fixed.
        # assert pq(r.content)('.meta .view-stats').length == 1, (
        #    'Add-on authors (not just owners) should be able to view stats')


class TestVotes(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(TestVotes, self).setUp()
        self.client.login(email='jbalogh@mozilla.com')
        args = ['fligtar', 'slug']
        Collection.objects.create(slug='slug', author_id=9945)
        self.c_url = reverse('collections.detail', args=args)
        self.up = reverse('collections.vote', args=args + ['up'])
        self.down = reverse('collections.vote', args=args + ['down'])

    def test_login_required(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.post(self.up), to=self.up)

    def test_post_required(self):
        r = self.client.get(self.up, follow=True)
        self.assert3xx(r, self.c_url)

    def check(self, upvotes=0, downvotes=0):
        c = Collection.objects.get(slug='slug', author=9945)
        assert c.upvotes == upvotes
        assert c.downvotes == downvotes
        assert CollectionVote.objects.filter(
            user=4043307, vote=1).count() == upvotes
        assert CollectionVote.objects.filter(
            user=4043307, vote=-1).count() == downvotes
        assert CollectionVote.objects.filter(
            user=4043307).count() == upvotes + downvotes

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
        self.assert3xx(r, self.c_url)

    def test_ajax_response(self):
        r = self.client.post_ajax(self.up, follow=True)
        assert not r.redirect_chain
        assert r.status_code == 200


class TestCRUD(TestCase):
    """Test the collection form."""
    fixtures = ('base/users', 'base/addon_3615', 'base/collections')

    def setUp(self):
        super(TestCRUD, self).setUp()
        self.add_url = reverse('collections.add')
        self.login_admin()
        # Oh god it's unicode.
        self.slug = u'\u05d0\u05d5\u05e1\u05e3'
        self.data = {
            'addon': 3615,
            'addon_comment': 'fff',
            'name': u'קווים תחתונים ומקפים בלבד',
            'slug': self.slug,
            'description': '',
            'listed': 'True'
        }

    def login_admin(self):
        assert self.client.login(email='admin@mozilla.com')

    def login_regular(self):
        assert self.client.login(email='regular@mozilla.com')

    def create_collection(self, **kw):
        self.data.update(kw)
        r = self.client.post(self.add_url, self.data, follow=True)
        assert r.status_code == 200
        return r

    @patch('olympia.bandwagon.views.statsd.incr')
    def test_create_collection_statsd(self, mock_incr):
        self.client.post(self.add_url, self.data, follow=True)
        mock_incr.assert_any_call('collections.created')

    def test_no_xss_in_edit_page(self):
        name = '"><script>alert(/XSS/);</script>'
        self.create_collection(name=name)
        collection = Collection.objects.get(slug=self.slug)
        assert collection.name == name
        url = reverse('collections.edit', args=['admin', collection.slug, ])
        r = self.client.get(url)
        self.assertContains(
            r,
            '&quot;&gt;&lt;script&gt;alert(/XSS/);&lt;/script&gt;'
        )
        assert name not in r.content

    def test_listing_xss(self):
        c = Collection.objects.get(id=80)
        assert self.client.login(email='clouserw@gmail.com')

        url = reverse('collections.watch', args=[c.author.username, c.slug])

        user = UserProfile.objects.get(id='10482')
        user.display_name = "<script>alert(1)</script>"
        user.save()

        r = self.client.post(url, follow=True)
        assert r.status_code == 200

        qs = CollectionWatcher.objects.filter(user__username='clouserw',
                                              collection=80)
        assert qs.count() == 1

        r = self.client.get('/en-US/firefox/collections/following/',
                            follow=True)

        assert '&lt;script&gt;alert' in r.content
        assert '<script>alert' not in r.content

    def test_add_fail(self):
        """
        If we input addons but fail at filling out the form, don't show
        invisible addons.
        """
        data = {'addon': 3615,
                'addon_comment': 'fff',
                'description': '',
                'listed': 'True'}

        r = self.client.post(self.add_url, data, follow=True)
        assert pq(r.content)('.errorlist li')[0].text == (
            'This field is required.')
        self.assertContains(r, 'Delicious')

    def test_default_locale(self):
        r = self.client.post('/he/firefox/collections/add',
                             self.data, follow=True)
        assert r.status_code == 200
        c = Collection.objects.get(slug=self.slug)
        assert c.default_locale == 'he'

    def test_fix_slug(self):
        self.data['slug'] = 'some slug'
        self.create_collection()
        Collection.objects.get(slug='some-slug')

    def test_showform(self):
        """Shows form if logged in."""
        r = self.client.get(self.add_url)
        assert r.status_code == 200

    def test_submit(self):
        """Test submission of addons."""
        # TODO(davedash): Test file uploads, test multiple addons.
        r = self.client.post(self.add_url, self.data, follow=True)
        assert r.request['PATH_INFO'].decode('utf-8') == (
            '/en-US/firefox/collections/admin/%s/' % self.slug)
        c = Collection.objects.get(slug=self.slug)
        assert unicode(c.name) == self.data['name']
        assert c.description == ''
        assert c.addons.all()[0].id == 3615

    def test_duplicate_slug(self):
        """Try the same thing twice.  AND FAIL"""
        self.client.post(self.add_url, self.data, follow=True)
        r = self.client.post(self.add_url, self.data, follow=True)
        assert r.context['form'].errors['slug'][0] == (
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
                      args=['regularuser', self.slug])
        r = self.client.post(
            url,
            {'contributor': 'admin@mozilla.com',
             'new_owner': 'admin@mozilla.com'},
            follow=True)
        assert r.status_code == 200
        # verify that user1's addon is slug + '-'
        c = Collection.objects.get(slug=self.slug)
        assert c.author_id == 4043307

    def test_edit(self):
        self.create_collection()
        url = reverse('collections.edit', args=['admin', self.slug])
        r = self.client.get(url, follow=True)
        assert r.status_code == 200

    def test_edit_contributors_form(self):
        self.create_collection()
        url = reverse('collections.edit', args=['admin', self.slug])
        r = self.client.get(url, follow=True)
        assert Collection.objects.get(slug=self.slug).author_id == (
            long(pq(r.content)('#contributor-ac').attr('data-owner')))

    def test_edit_post(self):
        """Test edit of collection."""
        self.create_collection()
        url = reverse('collections.edit', args=['admin', self.slug])

        r = self.client.post(url, {'name': 'HALP', 'slug': 'halp',
                                   'listed': True}, follow=True)
        assert r.status_code == 200
        c = Collection.objects.get(slug='halp')
        assert unicode(c.name) == 'HALP'

    def test_edit_description(self):
        self.create_collection()

        url = reverse('collections.edit', args=['admin', self.slug])
        self.data['description'] = 'abc'
        edit_url = Collection.objects.get(slug=self.slug).edit_url()
        r = self.client.post(url, self.data)
        self.assert3xx(r, edit_url, 302)
        assert unicode(Collection.objects.get(slug=self.slug).description) == (
            'abc')

    def test_edit_no_description(self):
        self.create_collection(description='abc')
        assert Collection.objects.get(slug=self.slug).description == 'abc'

        url = reverse('collections.edit', args=['admin', self.slug])
        self.data['description'] = ''
        edit_url = Collection.objects.get(slug=self.slug).edit_url()
        r = self.client.post(url, self.data)
        self.assert3xx(r, edit_url, 302)
        assert unicode(Collection.objects.get(slug=self.slug).description) == (
            '')

    def test_edit_spaces(self):
        """Let's put lots of spaces and see if they show up."""
        self.create_collection()
        url = reverse('collections.edit', args=['admin', self.slug])

        r = self.client.post(url,
                             {'name': '  H A L  P ', 'slug': '  halp  ',
                              'listed': True}, follow=True)
        assert r.status_code == 200
        c = Collection.objects.get(slug='halp')
        assert unicode(c.name) == 'H A L  P'

    def test_forbidden_edit(self):
        self.create_collection()
        self.login_regular()
        url_args = ['admin', self.slug]

        url = reverse('collections.edit', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.edit_addons', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.edit_contributors', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.edit_privacy', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.delete', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

    def test_acl_contributor(self):
        collection = self.create_collection().context['collection']
        regular_user = UserProfile.objects.get(email='regular@mozilla.com')
        collection.collectionuser_set.create(user=regular_user)
        self.login_regular()
        url_args = ['admin', self.slug]

        url = reverse('collections.edit', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 200
        assert r.context['form'] is None
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.edit_addons', args=url_args)
        r = self.client.get(url)
        # Passed acl check, but this view needs a POST.
        assert r.status_code == 405
        r = self.client.post(url, {'addon': 3615}, follow=True)
        assert r.status_code == 200

        url = reverse('collections.edit_contributors', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.edit_privacy', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

        url = reverse('collections.delete', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 403
        r = self.client.post(url)
        assert r.status_code == 403

    def test_acl_collections_edit(self):
        # Test users in group with 'Collections:Edit' are allowed.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Staff', rules='Collections:Edit')
        GroupUser.objects.create(user=user, group=group)
        r = self.client.post(self.add_url, self.data, follow=True)
        self.login_regular()
        url_args = ['admin', self.slug]

        url = reverse('collections.edit', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 200

        url = reverse('collections.edit_addons', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 405
        # Passed acl check, but this view needs a POST.

        url = reverse('collections.edit_contributors', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 405
        # Passed acl check, but this view needs a POST.

        url = reverse('collections.edit_privacy', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 405
        # Passed acl check, but this view needs a POST.

        url = reverse('collections.delete', args=url_args)
        r = self.client.get(url)
        assert r.status_code == 200

    def test_edit_favorites(self):
        r = self.client.get(reverse('collections.list'))
        fav = r.context['request'].user.favorites_collection()
        r = self.client.post(fav.edit_url(), {'name': 'xxx', 'listed': True})
        assert r.status_code == 302

        c = Collection.objects.get(id=fav.id)
        assert unicode(c.name) == 'xxx'

    def test_edit_contrib_tab(self):
        self.create_collection()
        url = reverse('collections.edit', args=['admin', self.slug])
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('.tab-nav li a[href$=users-edit]').length == 1
        assert doc('#users-edit').length == 1

    def test_edit_contrib_success_message(self):
        self.create_collection()
        url = reverse('collections.edit_contributors',
                      args=['admin', self.slug])
        r = self.client.post(url, {'contributor': 999,
                                   'application': 1,
                                   'type': 1},
                             follow=True)
        doc = pq(r.content)('.success')
        assert doc('h2').text() == 'Collection updated!'
        assert doc('p').text() == 'View your collection to see the changes.'

    def test_edit_no_contrib_tab(self):
        user = UserProfile.objects.get(email='admin@mozilla.com')

        favorites_url = user.favorites_collection().edit_url()
        response = self.client.get(favorites_url)
        doc = pq(response.content)
        assert not doc('.tab-nav li a[href$=users-edit]').length
        assert not doc('#users-edit').length

    def test_edit_addons_get(self):
        self.create_collection()
        url = reverse('collections.edit_addons', args=['admin', self.slug])
        r = self.client.get(url, follow=True)
        assert r.status_code == 405

    def test_edit_addons_post(self):
        self.create_collection()
        url = reverse('collections.edit_addons',
                      args=['admin', self.slug])
        r = self.client.post(url, {'addon': 3615}, follow=True)
        addon = Collection.objects.filter(slug=self.slug)[0].addons.all()[0]
        assert addon.id == 3615
        doc = pq(r.content)('.success')
        assert doc('h2').text() == 'Collection updated!'
        assert doc('p').text() == 'View your collection to see the changes.'

    def test_delete(self):
        self.create_collection()
        assert len(Collection.objects.filter(slug=self.slug)) == 1

        url = reverse('collections.delete',
                      args=['admin', self.slug])
        self.client.post(url, dict(sure=0))
        assert len(Collection.objects.filter(slug=self.slug)) == 1
        self.client.post(url, dict(sure='1'))
        assert len(Collection.objects.filter(slug=self.slug)) == 0

    def test_no_xss_in_delete_confirm_page(self):
        name = '"><script>alert(/XSS/);</script>'
        self.create_collection(name=name)
        collection = Collection.objects.get(slug=self.slug)
        assert collection.name == name
        url = reverse('collections.delete', args=['admin', collection.slug, ])
        r = self.client.get(url)
        self.assertContains(
            r,
            '&quot;&gt;&lt;script&gt;alert(/XSS/);&lt;/script&gt;'
        )
        assert name not in r.content

    @patch('olympia.access.acl.action_allowed')
    def test_admin(self, f):
        self.create_collection()
        url = reverse('collections.edit',
                      args=['admin', self.slug])
        r = self.client.get(url, follow=True)
        assert r.status_code == 200
        doc = pq(r.content)
        assert 'Admin Settings' in doc('form h3').text()

        r = self.client.post(url, dict(application=1, type=0), follow=True)
        assert r.status_code == 200

    def test_delete_link(self):
        # Create an addon by user 1.
        self.create_collection()

        url = reverse('collections.edit_contributors',
                      args=['admin', self.slug])
        self.client.post(
            url,
            {
                'contributor': 'regular@mozilla.com',
                'application': 1,
                'type': 1
            },
            follow=True)
        url = reverse('collections.edit', args=['admin', self.slug])

        r = self.client.get(url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert len(doc('a.delete')) == 2

        self.login_regular()
        r = self.client.get(url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert len(doc('a.delete')) == 0

    def test_form_uneditable_slug(self):
        """
        Editing a mobile or favorite collection should have an uneditable slug.
        """
        u = UserProfile.objects.get(username='admin')
        Collection(author=u, slug='mobile', type=amo.COLLECTION_MOBILE).save()
        url = reverse('collections.edit', args=['admin', 'mobile'])
        r = self.client.get(url, follow=True)
        doc = pq(r.content)
        assert len(doc('#id_slug')) == 0

    def test_form_uneditable_slug_submit(self):
        """
        Ignore the slug request change, if some jackass thinks he can change
        it.
        """
        u = UserProfile.objects.get(username='admin')
        Collection(author=u, slug='mobile', type=amo.COLLECTION_MOBILE).save()
        url = reverse('collections.edit', args=['admin', 'mobile'])
        self.client.post(url, {'name': 'HALP', 'slug': 'halp', 'listed': True},
                         follow=True)

        assert not Collection.objects.filter(slug='halp', author=u)
        assert Collection.objects.filter(slug='mobile', author=u)

    def test_no_changing_owners(self):
        self.login_regular()
        self.create_collection()
        c = Collection.objects.get(slug=self.slug)

        self.login_admin()
        r = self.client.post(c.edit_url(),
                             dict(name='new name', slug=self.slug,
                                  listed=True),
                             follow=True)
        assert r.status_code == 200

        newc = Collection.objects.get(slug=self.slug,
                                      author__username=c.author_username)
        assert unicode(newc.name) == 'new name'


class TestChangeAddon(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(TestChangeAddon, self).setUp()
        self.client.login(email='jbalogh@mozilla.com')
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
        self.assert3xx(request, url)

    def test_login_required(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.post(self.add), to=self.add)

    def test_post_required(self):
        r = self.client.get(self.add)
        assert r.status_code == 405

    def test_ownership(self):
        r = self.client.post(self.flig_add)
        assert r.status_code == 403

    def test_publisher(self):
        CollectionUser.objects.create(user_id=4043307, collection=self.flig)
        r = self.client.post_ajax(self.flig_add, {'addon_id': self.addon.id})
        self.check_redirect(r)

    def test_no_addon(self):
        r = self.client.post(self.add)
        assert r.status_code == 400

    def test_add_success(self):
        r = self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        self.check_redirect(r)
        c = Collection.objects.get(author__username='jbalogh', slug='mobile')
        assert self.addon in c.addons.all()
        assert c.addons.count() == 1

    def test_add_secretly(self):
        """
        When we add to a private collection, make sure we don't log anything.
        """
        self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        # There should be no log objects for this add-on
        assert len(ActivityLog.objects.for_addons(self.addon)) == 0

    def test_add_existing(self):
        r = self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        self.check_redirect(r)
        r = self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        self.check_redirect(r)
        c = Collection.objects.get(author__username='jbalogh', slug='mobile')
        assert self.addon in c.addons.all()
        assert c.addons.count() == 1

    def test_remove_secretly(self):
        """
        When we remove from a private collection, make sure we don't log
        anything.
        """
        self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        self.client.post_ajax(self.remove, {'addon_id': self.addon.id})
        # There should be no log objects for this add-on
        assert len(ActivityLog.objects.for_addons(self.addon)) == 0

    def test_remove_success(self):
        r = self.client.post_ajax(self.add, {'addon_id': self.addon.id})
        self.check_redirect(r)

        r = self.client.post_ajax(self.remove, {'addon_id': self.addon.id})
        self.check_redirect(r)

        c = Collection.objects.get(author__username='jbalogh', slug='mobile')
        assert c.addons.count() == 0

    def test_remove_nonexistent(self):
        r = self.client.post_ajax(self.remove, {'addon_id': self.addon.id})
        self.check_redirect(r)
        c = Collection.objects.get(author__username='jbalogh', slug='mobile')
        assert c.addons.count() == 0

    def test_no_ajax_response(self):
        r = self.client.post(self.add, {'addon_id': self.addon.id},
                             follow=True)
        self.assert3xx(r, reverse('collections.detail',
                                  args=['jbalogh', 'mobile']))


class AjaxTest(TestCase):
    fixtures = ('base/users', 'base/addon_3615',
                'base/addon_5299_gcal', 'base/collections')

    def setUp(self):
        super(AjaxTest, self).setUp()
        assert self.client.login(email='clouserw@gmail.com')
        self.user = UserProfile.objects.get(email='clouserw@gmail.com')
        self.other = UserProfile.objects.exclude(id=self.user.id)[0]

    def test_list_collections(self):
        r = self.client.get(
            reverse('collections.ajax_list') + '?addon_id=3615')
        doc = pq(r.content)
        assert doc('li.selected').attr('data-id') == '80'

    def test_add_collection(self):
        r = self.client.post_ajax(reverse('collections.ajax_add'),
                                  {'addon_id': 3615, 'id': 80}, follow=True)
        doc = pq(r.content)
        assert doc('li.selected').attr('data-id') == '80'

    def test_bad_collection(self):
        r = self.client.post(reverse('collections.ajax_add'), {'id': 'adfa'})
        assert r.status_code == 400

    def test_remove_collection(self):
        r = self.client.post(reverse('collections.ajax_remove'),
                             {'addon_id': 1843, 'id': 80}, follow=True)
        doc = pq(r.content)
        assert len(doc('li.selected')) == 0

    def test_new_collection(self):
        assert not Collection.objects.filter(slug='auniqueone')
        r = self.client.post(
            reverse('collections.ajax_new'),
            {'addon_id': 5299, 'name': 'foo', 'slug': 'auniqueone',
             'description': 'foobar', 'listed': True},
            follow=True)
        doc = pq(r.content)
        assert len(doc('li.selected')) == 1, (
            "The new collection is not selected.")
        assert Collection.objects.filter(slug='auniqueone')

    def test_add_other_collection(self):
        "403 when you try to add to a collection that isn't yours."
        c = Collection(author=self.other)
        c.save()

        r = self.client.post(reverse('collections.ajax_add'),
                             {'addon_id': 3615, 'id': c.id}, follow=True)
        assert r.status_code == 403

    def test_remove_other_collection(self):
        "403 when you try to add to a collection that isn't yours."
        c = Collection(author=self.other)
        c.save()

        r = self.client.post(reverse('collections.ajax_remove'),
                             {'addon_id': 3615, 'id': c.id}, follow=True)
        assert r.status_code == 403

    def test_ajax_list_no_addon_id(self):
        assert self.client.get(
            reverse('collections.ajax_list')).status_code == 400

    def test_ajax_list_bad_addon_id(self):
        url = reverse('collections.ajax_list') + '?addon_id=fff'
        assert self.client.get(url).status_code == 400


class TestWatching(TestCase):
    fixtures = ['base/users', 'base/collection_57181']

    def setUp(self):
        super(TestWatching, self).setUp()
        self.collection = c = Collection.objects.get(id=57181)
        self.url = reverse('collections.watch',
                           args=[c.author.username, c.slug])
        assert self.client.login(email='clouserw@gmail.com')

        self.qs = CollectionWatcher.objects.filter(user__username='clouserw',
                                                   collection=57181)
        assert self.qs.count() == 0

    def test_watch(self):
        r = self.client.post(self.url, follow=True)
        assert r.status_code == 200
        assert self.qs.count() == 1

    def test_unwatch(self):
        r = self.client.post(self.url, follow=True)
        assert r.status_code == 200
        r = self.client.post(self.url, follow=True)
        assert r.status_code == 200
        assert self.qs.count() == 0

    def test_amouser_watching(self):
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        response = self.client.get('/en-US/firefox/')
        assert tuple(response.context['user'].watching) == (57181,)

    def test_ajax_response(self):
        r = self.client.post_ajax(self.url, follow=True)
        assert r.status_code == 200
        assert json.loads(r.content) == {'watching': True}


class TestCollectionFeed(TestFeeds):
    fixtures = TestFeeds.fixtures

    def setUp(self):
        super(TestCollectionFeed, self).setUp()
        self.url = reverse('collections.list')
        self.rss_url = reverse('collections.rss')
        self.filter = CollectionFilter


class TestCollectionListing(TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'base/category',
                'base/featured', 'addons/featured', 'addons/listed',
                'base/collections', 'bandwagon/featured_collections']

    def setUp(self):
        super(TestCollectionListing, self).setUp()
        cache.clear()
        self.url = reverse('collections.list')

    def test_default_sort(self):
        r = self.client.get(self.url)
        assert r.context['sorting'] == 'featured'

    def test_featured_sort(self):
        r = self.client.get(urlparams(self.url, sort='featured'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'opt'
        assert sel.text() == 'Featured'

    def test_users_redirect(self):
        """Test that 'users' sort redirects to 'followers' sort."""
        r = self.client.get(urlparams(self.url, sort='users'))
        self.assert3xx(r, urlparams(self.url, sort='followers'), 301)

    def test_mostsubscribers_sort(self):
        r = self.client.get(urlparams(self.url, sort='followers'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'opt'
        assert sel.text() == 'Most Followers'
        c = r.context['collections'].object_list
        assert list(c) == sorted(c, key=lambda x: x.subscribers, reverse=True)

    def test_newest_sort(self):
        r = self.client.get(urlparams(self.url, sort='created'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'opt'
        assert sel.text() == 'Newest'
        c = r.context['collections'].object_list
        assert list(c) == sorted(c, key=lambda x: x.created, reverse=True)

    def test_name_sort(self):
        r = self.client.get(urlparams(self.url, sort='name'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'extra-opt'
        assert sel.text() == 'Name'
        c = r.context['collections'].object_list
        assert list(c) == sorted(c, key=lambda x: x.name)

    def test_updated_sort(self):
        r = self.client.get(urlparams(self.url, sort='updated'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'extra-opt'
        assert sel.text() == 'Recently Updated'
        c = r.context['collections'].object_list
        assert list(c) == sorted(c, key=lambda x: x.modified, reverse=True)

    def test_popular_sort(self):
        r = self.client.get(urlparams(self.url, sort='popular'))
        sel = pq(r.content)('#sorter ul > li.selected')
        assert sel.find('a').attr('class') == 'extra-opt'
        assert sel.text() == 'Recently Popular'
        c = r.context['collections'].object_list
        assert list(c) == (
            sorted(c, key=lambda x: x.weekly_subscribers, reverse=True))

    def _test_exclude_empty_collections(self, url):
        r = self.client.get(url)
        initial_length = len(r.context['collections'].object_list)
        Collection.objects.get(nickname='webdev').addons.clear()
        r = self.client.get(url)
        assert len(r.context['collections'].object_list) == initial_length - 1

    def test_exclude_empty_collections_newest_sort(self):
        url = urlparams(self.url, sort='created')
        self._test_exclude_empty_collections(url)

    def test_exclude_empty_collections_name_sort(self):
        url = urlparams(self.url, sort='name')
        self._test_exclude_empty_collections(url)

    def test_exclude_empty_collections_updated_sort(self):
        url = urlparams(self.url, sort='updated')
        self._test_exclude_empty_collections(url)

    def test_exclude_empty_collections_popular_sort(self):
        url = urlparams(self.url, sort='popular')
        self._test_exclude_empty_collections(url)

    def test_added_date(self):
        doc = pq(self.client.get(urlparams(self.url, sort='created')).content)
        assert doc('.items .item .updated').text().startswith('Added')

    def test_updated_date(self):
        d = pq(self.client.get(urlparams(self.url, sort='updated')).content)
        assert d('.items .item .updated').text().startswith('Updated')

    def test_mostsubscribers_adu_unit(self):
        d = pq(self.client.get(urlparams(self.url, sort='followers')).content)
        assert 'follower' in d('.items .item .followers').text()
        assert 'weekly follower' not in d('.items .item .followers').text()

    def test_popular_adu_unit(self):
        d = pq(self.client.get(urlparams(self.url, sort='popular')).content)
        assert 'weekly follower' in d('.items .item .followers').text()


class TestCollectionDetailFeed(TestCase):
    fixtures = ['base/collection_57181']

    def setUp(self):
        super(TestCollectionDetailFeed, self).setUp()
        self.collection = c = Collection.objects.get(id=57181)
        self.feed_url = reverse('collections.detail.rss',
                                args=[c.author.username, c.slug])

    def test_collection_feed(self):
        assert self.client.get(self.feed_url).status_code == 200

    def test_feed_redirect(self):
        r = self.client.get(self.collection.get_url_path() + '?format=rss')
        assert r.status_code == 301
        loc = r['Location']
        assert loc.endswith(self.feed_url), loc

    def test_private_collection(self):
        self.collection.update(listed=False)
        assert self.client.get(self.feed_url).status_code == 404

    def test_feed_json(self):
        theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        CollectionAddon.objects.create(addon=theme, collection=self.collection)
        res = self.client.get(self.collection.get_url_path() + 'format:json')
        data = json.loads(res.content)

        assert len(data['addons']) == 1
        assert data['addons'][0]['id'] == theme.id

        assert data['addons'][0]['type'] == 'background-theme'
        assert data['addons'][0]['theme']['id'] == (
            unicode(theme.persona.persona_id))

        assert data['addons'][0]['theme']['header']
        assert data['addons'][0]['theme']['footer'] == ''


class TestCollectionForm(TestCase):
    fixtures = ['base/collection_57181', 'users/test_backends']

    @patch('olympia.amo.models.UncachedModelBase.update')
    def test_icon(self, update_mock):
        collection = Collection.objects.get(pk=57181)
        # TODO(andym): altering this form is too complicated, can we simplify?
        form = forms.CollectionForm(
            {'listed': collection.listed,
             'slug': collection.slug,
             'name': collection.name},
            instance=collection,
            files={'icon': get_uploaded_file('transparent.png')},
            initial={'author': collection.author,
                     'application': collection.application})
        assert form.is_valid()
        form.save()
        assert update_mock.called

    def test_icon_invalid_though_content_type_is_correct(self):
        collection = Collection.objects.get(pk=57181)
        # This file is not an image at all, but we'll try to upload it with an
        # image mime type. It should not work.
        fake_image = get_uploaded_file('non-image.png')
        assert fake_image.content_type == 'image/png'
        form = forms.CollectionForm(
            {'listed': collection.listed,
             'slug': collection.slug,
             'name': collection.name},
            instance=collection,
            files={'icon': fake_image},
            initial={'author': collection.author,
                     'application': collection.application})
        assert not form.is_valid()
        assert form.errors == {'icon': [u'Icons must be either PNG or JPG.']}

    def test_icon_invalid_gif(self):
        collection = Collection.objects.get(pk=57181)
        form = forms.CollectionForm(
            {'listed': collection.listed,
             'slug': collection.slug,
             'name': collection.name},
            instance=collection,
            files={'icon': get_uploaded_file('animated.gif')},
            initial={'author': collection.author,
                     'application': collection.application})
        assert not form.is_valid()
        assert form.errors == {'icon': [u'Icons must be either PNG or JPG.']}

    def test_icon_invalid_animated(self):
        collection = Collection.objects.get(pk=57181)
        form = forms.CollectionForm(
            {'listed': collection.listed,
             'slug': collection.slug,
             'name': collection.name},
            instance=collection,
            files={'icon': get_uploaded_file('animated.png')},
            initial={'author': collection.author,
                     'application': collection.application})
        assert not form.is_valid()
        assert form.errors == {'icon': [u'Icons cannot be animated.']}

    def test_denied_name(self):
        form = forms.CollectionForm()
        form.cleaned_data = {'name': 'IE6Fan'}
        with self.assertRaisesRegexp(ValidationError,
                                     'This name cannot be used.'):
            form.clean_name()

    def test_denied_name_contains(self):
        form = forms.CollectionForm()
        form.cleaned_data = {'name': 'IE6fanBoy'}
        with self.assertRaisesRegexp(ValidationError,
                                     'This name cannot be used.'):
            form.clean_name()

    def test_clean_description(self):
        # No links, no problems.
        form = forms.CollectionForm()
        form.cleaned_data = {'description': 'some description, no links!'}
        assert form.clean_description() == 'some description, no links!'

        # No links allowed: raise on text links.
        form.cleaned_data = {'description': 'http://example.com'}
        with self.assertRaisesRegexp(ValidationError, 'No links are allowed'):
            form.clean_description()

        # No links allowed: raise on URLs.
        form.cleaned_data = {
            'description': '<a href="http://example.com">example.com</a>'}
        with self.assertRaisesRegexp(ValidationError, 'No links are allowed'):
            form.clean_description()

    def test_honeypot_not_required(self):
        author = UserProfile.objects.get(pk=9945)

        form = forms.CollectionForm(
            initial={'author': author},
            data={
                'name': 'test collection',
                'slug': 'test-collection',
                'listed': False,
            }
        )

        assert form.is_valid()

    def test_honeypot_fails_on_entry(self):
        author = UserProfile.objects.get(pk=9945)

        form = forms.CollectionForm(
            initial={'author': author},
            data={
                'name': 'test collection',
                'slug': 'test-collection',
                'listed': False,
                'your_name': "I'm a super dumb bot",
            }
        )

        assert not form.is_valid()
        assert 'spam' in form.errors['__all__'][0]

    @patch('olympia.bandwagon.forms.statsd.incr')
    def test_honeypot_statsd_incr(self, mock_incr):
        author = UserProfile.objects.get(pk=9945)

        form = forms.CollectionForm(
            initial={'author': author},
            data={
                'name': 'test collection',
                'slug': 'test-collection',
                'listed': False,
                'your_name': "I'm a super dumb bot",
            }
        )

        assert not form.is_valid()

        mock_incr.assert_any_call('collections.honeypotted')


class TestCollectionViewSetList(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.url = reverse(
            'collection-list', kwargs={'user_pk': self.user.pk})
        super(TestCollectionViewSetList, self).setUp()

    def test_basic(self):
        collection_factory(author=self.user)
        collection_factory(author=self.user)
        collection_factory(author=self.user)
        collection_factory(author=user_factory())  # Not our collection.
        Collection.objects.all().count() == 4

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data['results']) == 3

    def test_no_auth(self):
        collection_factory(author=self.user)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_different_user(self):
        random_user = user_factory()
        other_url = reverse('collection-list',
                            kwargs={'user_pk': random_user.pk})
        collection_factory(author=random_user)

        self.client.login_api(self.user)
        response = self.client.get(other_url)
        assert response.status_code == 403

    def test_admin(self):
        random_user = user_factory()
        other_url = reverse('collection-list',
                            kwargs={'user_pk': random_user.pk})
        collection_factory(author=random_user)

        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        response = self.client.get(other_url)
        assert response.status_code == 200
        assert len(response.data['results']) == 1

    def test_404(self):
        # Invalid user.
        url = reverse(
            'collection-list', kwargs={'user_pk': self.user.pk + 66})

        # Not logged in.
        response = self.client.get(url)
        assert response.status_code == 401

        # Logged in
        self.client.login_api(self.user)
        response = self.client.get(url)
        assert response.status_code == 404

    def test_sort(self):
        col_a = collection_factory(author=self.user)
        col_b = collection_factory(author=self.user)
        col_c = collection_factory(author=self.user)
        col_a.update(modified=self.days_ago(3))
        col_b.update(modified=self.days_ago(1))
        col_c.update(modified=self.days_ago(6))

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        # should be b a c because 1, 3, 6 days ago.
        assert response.data['results'][0]['uuid'] == col_b.uuid
        assert response.data['results'][1]['uuid'] == col_a.uuid
        assert response.data['results'][2]['uuid'] == col_c.uuid

    def test_with_addons_is_ignored(self):
        collection_factory(author=self.user)
        self.client.login_api(self.user)
        response = self.client.get(self.url + '?with_addons')
        assert response.status_code == 200, response.data
        assert 'addons' not in response.data['results'][0]


class TestCollectionViewSetDetail(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = self._get_url(self.user, self.collection)
        super(TestCollectionViewSetDetail, self).setUp()

    def _get_url(self, user, collection):
        return reverse(
            'collection-detail', kwargs={
                'user_pk': user.pk, 'slug': collection.slug})

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id

    def test_no_id_lookup(self):
        collection = collection_factory(author=self.user, slug='999')
        id_url = reverse(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': collection.id})
        response = self.client.get(id_url)
        assert response.status_code == 404
        slug_url = reverse(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': collection.slug})
        response = self.client.get(slug_url)
        assert response.status_code == 200
        assert response.data['id'] == collection.id

    def test_not_listed(self):
        self.collection.update(listed=False)

        # not logged in
        response = self.client.get(self.url)
        assert response.status_code == 401

        # logged in
        random_user = user_factory()
        self.client.login_api(random_user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_not_listed_self(self):
        self.collection.update(listed=False)

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id

    def test_not_listed_admin(self):
        random_user = user_factory()
        collection = collection_factory(author=random_user, listed=False)

        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        response = self.client.get(self._get_url(random_user, collection))
        assert response.status_code == 200
        assert response.data['id'] == collection.id

    def test_not_listed_contributor(self):
        self.collection.update(listed=False)

        random_user = user_factory()
        self.client.login_api(random_user)
        # Not their collection so not allowed.
        response = self.client.get(self.url)
        assert response.status_code == 403

        CollectionUser.objects.create(collection=self.collection,
                                      user=random_user)
        # Now they can access it.
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id

    def test_404(self):
        # Invalid user.
        response = self.client.get(reverse(
            'collection-detail', kwargs={
                'user_pk': self.user.pk + 66, 'slug': self.collection.slug}))
        assert response.status_code == 404
        # Invalid collection.
        response = self.client.get(reverse(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': 'hello'}))
        assert response.status_code == 404

    def test_with_addons(self):
        addon = addon_factory()
        self.collection.add_addon(addon)
        response = self.client.get(self.url + '?with_addons')
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id
        addon_data = response.data['addons'][0]['addon']
        assert addon_data['id'] == addon.id
        assert isinstance(addon_data['name'], dict)
        assert addon_data['name'] == {'en-US': unicode(addon.name)}

        # Now test the limit of addons returned
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        response = self.client.get(self.url + '?with_addons')
        assert len(response.data['addons']) == 4
        patched_drf_setting = dict(settings.REST_FRAMEWORK)
        patched_drf_setting['PAGE_SIZE'] = 3
        with django.test.override_settings(REST_FRAMEWORK=patched_drf_setting):
            response = self.client.get(self.url + '?with_addons')
            assert len(response.data['addons']) == 3

    def test_with_addons_and_wrap_outgoing_links_and_lang(self):
        addon = addon_factory(
            support_url='http://support.example.com',
            homepage='http://homepage.example.com')
        self.collection.add_addon(addon)
        response = self.client.get(
            self.url + '?with_addons&lang=en-US&wrap_outgoing_links')
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id
        addon_data = response.data['addons'][0]['addon']
        assert addon_data['id'] == addon.id
        assert isinstance(addon_data['name'], basestring)
        assert addon_data['name'] == unicode(addon.name)
        assert isinstance(addon_data['homepage'], basestring)
        assert addon_data['homepage'] == get_outgoing_url(
            unicode(addon.homepage))
        assert isinstance(addon_data['support_url'], basestring)
        assert addon_data['support_url'] == get_outgoing_url(
            unicode(addon.support_url))


class CollectionViewSetDataMixin(object):
    client_class = APITestClient
    data = {
        'name': {'fr': u'lé $túff', 'en-US': u'$tuff'},
        'description': {'fr': u'Un dis une dát', 'en-US': u'dis n dat'},
        'slug': u'stuff',
        'public': True,
        'default_locale': 'fr',
    }

    def setUp(self):
        self.url = self.get_url(self.user)
        super(CollectionViewSetDataMixin, self).setUp()

    def send(self, url=None, data=None):
        raise NotImplementedError

    def get_url(self, user):
        raise NotImplementedError

    @property
    def user(self):
        if not hasattr(self, '_user'):
            self._user = user_factory()
        return self._user

    def check_data(self, collection, data, json):
        for prop, value in data.iteritems():
            assert json[prop] == value

        with self.activate('fr'):
            collection = collection.reload()
            assert collection.name == data['name']['fr']
            assert collection.description == data['description']['fr']
            assert collection.slug == data['slug']
            assert collection.listed == data['public']
            assert collection.default_locale == data['default_locale']

    def test_no_auth(self):
        response = self.send()
        assert response.status_code == 401

    def test_update_name_invalid(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(name=u'   ')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['Name cannot be empty.']}

        # Passing a dict of localised values
        data.update(name={'en-US': u'   '})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['Name cannot be empty.']}

    def test_biography_no_links(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(description='<a href="https://google.com">google</a>')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': ['No links are allowed.']}

        data.update(description={
            'en-US': '<a href="https://google.com">google</a>'})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': ['No links are allowed.']}

    def test_slug_valid(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(slug=u'£^@')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'slug': [u'The custom URL must consist of letters, numbers, '
                     u'underscores or hyphens.']}

    def test_slug_unique(self):
        collection_factory(author=self.user, slug='edam')
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(slug=u'edam')
        response = self.send(data=data)
        assert response.status_code == 400
        assert u'This custom URL is already in use' in (
            ','.join(json.loads(response.content)['non_field_errors']))


class TestCollectionViewSetCreate(CollectionViewSetDataMixin, TestCase):

    def send(self, url=None, data=None):
        return self.client.post(url or self.url, data or self.data)

    def get_url(self, user):
        return reverse('collection-list', kwargs={'user_pk': user.pk})

    def test_basic_create(self):
        self.client.login_api(self.user)
        response = self.send()
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        self.check_data(collection, self.data, json.loads(response.content))
        assert collection.author.id == self.user.id
        assert collection.uuid

    def test_create_minimal(self):
        self.client.login_api(self.user)
        data = {
            'name': u'this',
            'slug': u'minimal',
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.name == data['name']
        assert collection.slug == data['slug']

    def test_create_cant_set_readonly(self):
        self.client.login_api(self.user)
        data = {
            'name': u'this',
            'slug': u'minimal',
            'addon_count': 99,  # In the serializer but read-only.
            'subscribers': 999,  # Not in the serializer.
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.addon_count != 99
        assert collection.subscribers != 999

    def test_different_account(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        url = self.get_url(different_user)
        response = self.send(url=url)
        assert response.status_code == 403

    def test_admin_create_fails(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        url = self.get_url(random_user)
        response = self.send(url=url)
        assert response.status_code == 403

    def test_create_numeric_slug(self):
        self.client.login_api(self.user)
        data = {
            'name': u'this',
            'slug': u'1',
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.name == data['name']
        assert collection.slug == data['slug']


class TestCollectionViewSetPatch(CollectionViewSetDataMixin, TestCase):

    def setUp(self):
        self.collection = collection_factory(author=self.user)
        super(TestCollectionViewSetPatch, self).setUp()

    def send(self, url=None, data=None):
        return self.client.patch(url or self.url, data or self.data)

    def get_url(self, user):
        return reverse(
            'collection-detail', kwargs={
                'user_pk': user.pk, 'slug': self.collection.slug})

    def test_basic_patch(self):
        self.client.login_api(self.user)
        original = self.client.get(self.url).content
        response = self.send()
        assert response.status_code == 200
        assert response.content != original
        self.collection = self.collection.reload()
        self.check_data(self.collection, self.data,
                        json.loads(response.content))

    def test_different_account(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        url = self.get_url(different_user)
        response = self.send(url=url)
        assert response.status_code == 403

    def test_admin_patch(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        url = self.get_url(random_user)
        original = self.client.get(url).content
        response = self.send(url=url)
        assert response.status_code == 200
        assert response.content != original
        self.collection = self.collection.reload()
        self.check_data(self.collection, self.data,
                        json.loads(response.content))
        # Just double-check we didn't steal their collection
        assert self.collection.author.id == random_user.id

    def test_contributor_patch_fails(self):
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        CollectionUser.objects.create(collection=self.collection,
                                      user=self.user)
        url = self.get_url(random_user)
        # Check setup is good and we can access the collection okay.
        get_response = self.client.get(url)
        assert get_response.status_code == 200
        # But can't patch it.
        response = self.send(url=url)
        assert response.status_code == 403


class TestCollectionViewSetDelete(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = self.get_url(self.user)
        super(TestCollectionViewSetDelete, self).setUp()

    def get_url(self, user):
        return reverse(
            'collection-detail', kwargs={
                'user_pk': user.pk, 'slug': self.collection.slug})

    def test_delete(self):
        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert not Collection.objects.filter(id=self.collection.id).exists()

    def test_no_auth(self):
        response = self.client.delete(self.url)
        assert response.status_code == 401

    def test_different_account_fails(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        url = self.get_url(different_user)
        response = self.client.delete(url)
        assert response.status_code == 403

    def test_admin_delete(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        url = self.get_url(random_user)
        response = self.client.delete(url)
        assert response.status_code == 204
        assert not Collection.objects.filter(id=self.collection.id).exists()

    def test_contributor_fails(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        CollectionUser.objects.create(collection=self.collection,
                                      user=self.user)
        url = self.get_url(different_user)
        # Check setup is good and we can access the collection okay.
        get_response = self.client.get(url)
        assert get_response.status_code == 200
        # But can't delete it.
        response = self.client.delete(url)
        assert response.status_code == 403


class CollectionAddonViewSetMixin(object):
    def check_response(self, response):
        raise NotImplementedError

    def send(self, url):
        # List and Detail do this.  Override for other verbs.
        return self.client.get(url)

    def test_basic(self):
        self.check_response(self.send(self.url))

    def test_not_listed_not_logged_in(self):
        self.collection.update(listed=False)
        response = self.send(self.url)
        assert response.status_code == 401

    def test_not_listed_different_user(self):
        self.collection.update(listed=False)
        different_user = user_factory()
        self.client.login_api(different_user)
        response = self.send(self.url)
        assert response.status_code == 403

    def test_not_listed_self(self):
        self.collection.update(listed=False)
        self.client.login_api(self.user)
        self.check_response(self.send(self.url))

    def test_not_listed_admin(self):
        admin_user = user_factory()
        self.grant_permission(admin_user, 'Collections:Edit')
        self.client.login_api(admin_user)
        self.check_response(self.send(self.url))

    def test_contributor(self):
        random_user = user_factory()
        CollectionUser.objects.create(collection=self.collection,
                                      user=random_user)
        self.client.login_api(random_user)
        self.check_response(self.send(self.url))


class TestCollectionAddonViewSetList(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon_a = addon_factory(name=u'anteater')
        self.addon_b = addon_factory(name=u'baboon')
        self.addon_c = addon_factory(name=u'cheetah')
        self.addon_disabled = addon_factory(name=u'antelope_disabled')
        self.addon_deleted = addon_factory(name=u'buffalo_deleted')
        self.addon_pending = addon_factory(name=u'pelican_pending')

        # Set a few more languages on our add-ons to test sorting
        # a bit better. https://github.com/mozilla/addons-server/issues/8354
        self.addon_a.name = {'de': u'Ameisenbär'}
        self.addon_a.save()

        self.addon_b.name = {'de': u'Pavian'}
        self.addon_b.save()

        self.addon_c.name = {'de': u'Gepard'}
        self.addon_c.save()

        self.collection.add_addon(self.addon_a)
        self.collection.add_addon(self.addon_disabled)
        self.collection.add_addon(self.addon_b)
        self.collection.add_addon(self.addon_deleted)
        self.collection.add_addon(self.addon_c)
        self.collection.add_addon(self.addon_pending)

        # Set up our filtered-out-by-default addons
        self.addon_disabled.update(disabled_by_user=True)
        self.addon_deleted.delete()
        self.addon_pending.current_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW)

        self.url = reverse(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug})
        super(TestCollectionAddonViewSetList, self).setUp()

    def check_response(self, response):
        assert response.status_code == 200, self.url
        assert len(response.data['results']) == 3

    def test_404(self):
        # Invalid user.
        response = self.client.get(reverse(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk + 66,
                'collection_slug': self.collection.slug}))
        assert response.status_code == 404
        # Invalid collection.
        response = self.client.get(reverse(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': 'hello'}))
        assert response.status_code == 404

    def check_result_order(self, response, first, second, third):
        results = response.data['results']
        assert results[0]['addon']['id'] == first.id
        assert results[1]['addon']['id'] == second.id
        assert results[2]['addon']['id'] == third.id
        assert len(response.data['results']) == 3

    def test_sorting(self):
        self.addon_a.update(weekly_downloads=500)
        self.addon_b.update(weekly_downloads=1000)
        self.addon_c.update(weekly_downloads=100)

        self.client.login_api(self.user)

        # First default sort
        self.check_result_order(
            self.client.get(self.url),
            self.addon_b, self.addon_a, self.addon_c)

        # Popularity ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=popularity'),
            self.addon_c, self.addon_a, self.addon_b)

        # Popularity descending (same as default)
        self.check_result_order(
            self.client.get(self.url + '?sort=-popularity'),
            self.addon_b, self.addon_a, self.addon_c)

        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_a).update(
            created=self.days_ago(1))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_b).update(
            created=self.days_ago(3))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_c).update(
            created=self.days_ago(2))

        # Added ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=added'),
            self.addon_b, self.addon_c, self.addon_a)

        # Added descending
        self.check_result_order(
            self.client.get(self.url + '?sort=-added'),
            self.addon_a, self.addon_c, self.addon_b)

        # Name ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=name'),
            self.addon_a, self.addon_b, self.addon_c)

        # Name descending
        self.check_result_order(
            self.client.get(self.url + '?sort=-name'),
            self.addon_c, self.addon_b, self.addon_a)

        # Name ascending, German
        self.check_result_order(
            self.client.get(self.url + '?sort=name&lang=de'),
            self.addon_a, self.addon_c, self.addon_b)

        # Name descending, German
        self.check_result_order(
            self.client.get(self.url + '?sort=-name&lang=de'),
            self.addon_b, self.addon_c, self.addon_a)

    def test_only_one_sort_parameter_supported(self):
        response = self.client.get(self.url + '?sort=popularity,name')

        assert response.status_code == 400
        assert response.data == [
            'You can only specify one "sort" argument. Multiple orderings '
            'are not supported']

    def test_with_deleted_or_with_hidden(self):
        response = self.send(self.url)
        assert response.status_code == 200
        # Normal
        assert len(response.data['results']) == 3

        response = self.send(self.url + '?filter=all')
        assert response.status_code == 200
        # Now there should be 2 extra
        assert len(response.data['results']) == 5

        response = self.send(self.url + '?filter=all_with_deleted')
        assert response.status_code == 200
        # And one more still - with_deleted gets you with_hidden too.
        assert len(response.data['results']) == 6
        all_addons_ids = {
            self.addon_a.id, self.addon_b.id, self.addon_c.id,
            self.addon_disabled.id, self.addon_deleted.id,
            self.addon_pending.id}
        result_ids = {
            result['addon']['id'] for result in response.data['results']}
        assert all_addons_ids == result_ids


class TestCollectionAddonViewSetDetail(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetDetail, self).setUp()

    def check_response(self, response):
        assert response.status_code == 200, self.url
        assert response.data['addon']['id'] == self.addon.id

    def test_with_slug(self):
        self.url = reverse(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.slug})
        self.test_basic()

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()


class TestCollectionAddonViewSetCreate(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = reverse(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug})
        self.addon = addon_factory()
        super(TestCollectionAddonViewSetCreate, self).setUp()

    def check_response(self, response):
        assert response.status_code == 201, response.content
        assert CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon.id).exists()

    def send(self, url, data=None):
        data = data or {'addon': self.addon.pk}
        return self.client.post(url, data=data)

    def test_basic(self):
        assert not CollectionAddon.objects.filter(
            collection=self.collection.id).exists()
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_add_with_comments(self):
        self.client.login_api(self.user)
        response = self.send(self.url,
                             data={'addon': self.addon.pk,
                                   'notes': 'its good!'})
        self.check_response(response)
        collection_addon = CollectionAddon.objects.get(
            collection=self.collection.id, addon=self.addon.id)
        assert collection_addon.addon == self.addon
        assert collection_addon.collection == self.collection
        assert collection_addon.comments == 'its good!'

    def test_fail_when_no_addon(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'notes': ''})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': [u'This field is required.']}

    def test_fail_when_not_public_addon(self):
        self.client.login_api(self.user)
        self.addon.update(status=amo.STATUS_NULL)
        response = self.send(self.url)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': ['Invalid pk or slug "%s" - object does not exist.' %
                      self.addon.pk]}

    def test_fail_when_invalid_addon(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': 3456})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': ['Invalid pk or slug "%s" - object does not exist.' %
                      3456]}

    def test_with_slug(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': self.addon.slug})
        self.check_response(response)

    def test_uniqueness_message(self):
        CollectionAddon.objects.create(
            collection=self.collection, addon=self.addon)
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': self.addon.slug})
        assert response.status_code == 400
        assert response.data == {
            u'non_field_errors':
                [u'This add-on already belongs to the collection']
        }


class TestCollectionAddonViewSetPatch(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetPatch, self).setUp()

    def check_response(self, response, data=None):
        data = data or {'notes': 'it does things'}
        assert response.status_code == 200, response.content
        collection_addon = CollectionAddon.objects.get(
            collection=self.collection.id)
        assert collection_addon.addon == self.addon
        assert collection_addon.collection == self.collection
        assert collection_addon.comments == data['notes']

    def send(self, url, data=None):
        data = data or {'notes': 'it does things'}
        return self.client.patch(url, data=data)

    def test_basic(self):
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_cant_change_addon(self):
        self.client.login_api(self.user)
        new_addon = addon_factory()
        response = self.send(self.url,
                             data={'addon': new_addon.id})
        self.check_response(response, data={'notes': None})

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()


class TestCollectionAddonViewSetDelete(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetDelete, self).setUp()

    def check_response(self, response):
        assert response.status_code == 204
        assert not CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon).exists()

    def send(self, url):
        return self.client.delete(url)

    def test_basic(self):
        assert CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon).exists()
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()
