import json
import os

from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.db.models import Q

import mock

from pyquery import PyQuery as pq

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.forms import AddonFormBasic
from olympia.addons.models import (
    Addon, AddonCategory, AddonDependency, Category)
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.tests import (
    TestCase, addon_factory, formset, initial, req_factory_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import image_size
from olympia.bandwagon.models import (
    Collection, CollectionAddon, FeaturedCollection)
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.devhub.views import edit_theme
from olympia.tags.models import AddonTag, Tag
from olympia.users.models import UserProfile
from olympia.versions.models import VersionPreview


class BaseTestEdit(TestCase):
    fixtures = ['base/users', 'base/addon_3615',
                'base/addon_5579', 'base/addon_3615_categories']
    listed = True
    __test__ = False  # this is an abstract test case

    def setUp(self):
        super(BaseTestEdit, self).setUp()
        assert self.client.login(email='del@icio.us')

        addon = self.get_addon()
        if self.listed:
            self.make_addon_listed(addon)
            ac = AddonCategory.objects.filter(addon=addon, category__id=22)[0]
            ac.feature = False
            ac.save()
            AddonCategory.objects.filter(addon=addon,
                                         category__id__in=[1, 71]).delete()

            self.tags = ['tag3', 'tag2', 'tag1']
            for t in self.tags:
                Tag(tag_text=t).save_tag(addon)
        else:
            self.make_addon_unlisted(addon)
            addon.save()

        self.user = UserProfile.objects.get(pk=55021)
        self.addon = self.get_addon()
        self.url = self.addon.get_dev_url()

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def get_url(self, section, edit=False):
        args = [self.addon.slug, section]
        if edit:
            args.append('edit')
        return reverse('devhub.addons.section', args=args)


class BaseTestEditBasic(BaseTestEdit):
    __test__ = False  # this is an abstract test case

    def setUp(self):
        super(BaseTestEditBasic, self).setUp()
        self.basic_edit_url = self.get_url('basic', edit=True)
        if self.listed:
            ctx = self.client.get(self.basic_edit_url).context
            self.cat_initial = initial(ctx['cat_form'].initial_forms[0])

    def get_dict(self, **kw):
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary'}
        if self.listed:
            fs = formset(self.cat_initial, initial_count=1)
            result.update({'is_experimental': True,
                           'requires_payment': True,
                           'tags': ', '.join(self.tags)})
            result.update(fs)

        result.update(**kw)
        return result

    def test_edit_page_not_editable(self):
        # The /edit page is the entry point for the individual edit sections,
        # and should never display the actual forms, so it should always pass
        # editable=False to the templates it renders.
        # See https://github.com/mozilla/addons-server/issues/6208
        response = self.client.get(self.url)
        assert response.context['editable'] is False

    def test_redirect(self):
        # /addon/:id => /addon/:id/edit
        response = self.client.get(
            '/en-US/developers/addon/3615/', follow=True)
        self.assert3xx(response, self.url, 301)

    def test_edit(self):
        old_name = self.addon.name
        data = self.get_dict()

        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        addon = self.get_addon()

        assert unicode(addon.name) == data['name']
        assert addon.name.id == old_name.id

        assert unicode(addon.summary) == data['summary']
        assert unicode(addon.slug) == data['slug']

        if self.listed:
            assert [unicode(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_check_description(self):
        # Make sure bug 629779 doesn't return.
        old_desc = self.addon.description
        data = self.get_dict()

        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        addon = self.get_addon()

        assert addon.description == old_desc

    def test_edit_slug_invalid(self):
        old_edit = self.basic_edit_url
        data = self.get_dict(name='', slug='invalid')
        response = self.client.post(self.basic_edit_url, data)
        doc = pq(response.content)
        assert doc('form').attr('action') == old_edit

    def test_edit_slug_valid(self):
        old_edit = self.basic_edit_url
        data = self.get_dict(slug='valid')
        response = self.client.post(self.basic_edit_url, data)
        doc = pq(response.content)
        assert doc('form').attr('action') != old_edit

    def test_edit_summary_escaping(self):
        data = self.get_dict()
        data['summary'] = '<b>oh my</b>'
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        addon = self.get_addon()

        # Fetch the page so the LinkifiedTranslation gets in cache.
        response = self.client.get(
            reverse('devhub.addons.edit', args=[addon.slug]))
        assert pq(response.content)('[data-name=summary]').html().strip() == (
            '<span lang="en-us">&lt;b&gt;oh my&lt;/b&gt;</span>')

        # Now make sure we don't have escaped content in the rendered form.
        form = AddonFormBasic(instance=addon, request=req_factory_factory('/'))
        html = pq('<body>%s</body>' % form['summary'])('[lang="en-us"]').html()
        assert html.strip() == '<b>oh my</b>'

    def test_edit_as_developer(self):
        self.login('regular@mozilla.com')
        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        # Make sure we get errors when they are just regular users.
        assert response.status_code == 403 if self.listed else 404

        devuser = UserProfile.objects.get(pk=999)
        self.get_addon().addonuser_set.create(
            user=devuser, role=amo.AUTHOR_ROLE_DEV)
        response = self.client.post(self.basic_edit_url, data)

        assert response.status_code == 200
        addon = self.get_addon()

        assert unicode(addon.name) == data['name']
        assert unicode(addon.summary) == data['summary']
        assert unicode(addon.slug) == data['slug']

        if self.listed:
            assert [unicode(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_name_required(self):
        data = self.get_dict(name='', slug='test_addon')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'name', 'This field is required.')
        assert self.get_addon().name != ''

    def test_edit_name_spaces(self):
        data = self.get_dict(name='    ', slug='test_addon')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'name', 'This field is required.')

    def test_edit_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')
        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'slug',
            'This slug is already in use. Please choose another.')

    def test_edit_name_not_empty(self):
        data = self.get_dict(name='', slug=self.addon.slug,
                             summary=self.addon.summary)
        response = self.client.post(self.basic_edit_url, data)
        self.assertFormError(
            response, 'form', 'name', 'This field is required.')

    def test_edit_name_max_length(self):
        data = self.get_dict(name='xx' * 70, slug=self.addon.slug,
                             summary=self.addon.summary)
        response = self.client.post(self.basic_edit_url, data)
        self.assertFormError(response, 'form', 'name',
                             'Ensure this value has at most 50 '
                             'characters (it has 140).')

    def test_edit_summary_max_length(self):
        data = self.get_dict(name=self.addon.name, slug=self.addon.slug,
                             summary='x' * 251)
        response = self.client.post(self.basic_edit_url, data)
        self.assertFormError(response, 'form', 'summary',
                             'Ensure this value has at most 250 '
                             'characters (it has 251).')

    def test_nav_links(self, show_compat_reporter=True):
        if self.listed:
            links = [
                self.addon.get_dev_url('edit'),  # Edit Information
                self.addon.get_dev_url('owner'),  # Manage Authors
                self.addon.get_dev_url('versions'),  # Manage Status & Versions
                self.addon.get_url_path(),  # View Listing
                reverse('devhub.feed', args=[self.addon.slug]),  # View Recent
                reverse('stats.overview', args=[self.addon.slug]),  # Stats
            ]
        else:
            links = [
                self.addon.get_dev_url('edit'),  # Edit Information
                self.addon.get_dev_url('owner'),  # Manage Authors
                self.addon.get_dev_url('versions'),  # Manage Status & Versions
                reverse('devhub.feed', args=[self.addon.slug]),  # View Recent
            ]

        if show_compat_reporter:
            # Compatibility Reporter. Only shown for legacy extensions.
            links.append(
                reverse('compat.reporter_detail', args=[self.addon.guid]))

        response = self.client.get(self.url)
        doc_links = [
            unicode(a.attrib['href'])
            for a in pq(response.content)('#edit-addon-nav').find('li a')]
        assert links == doc_links

    def test_nav_links_webextensions(self):
        self.addon.find_latest_version(None).files.update(is_webextension=True)
        self.test_nav_links(show_compat_reporter=False)

    def _feature_addon(self, addon_id=3615):
        c_addon = CollectionAddon.objects.create(
            addon_id=addon_id, collection=Collection.objects.create())
        FeaturedCollection.objects.create(collection=c_addon.collection,
                                          application=amo.FIREFOX.id)


class TagTestsMixin(object):
    def test_edit_add_tag(self):
        count = ActivityLog.objects.all().count()
        self.tags.insert(0, 'tag4')
        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        result = pq(response.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))
        html = ('<a href="/en-US/firefox/tag/tag4">tag4</a> added to '
                '<a href="/en-US/firefox/addon/test_slug/">new name</a>.')
        assert ActivityLog.objects.for_addons(self.addon).get(
            action=amo.LOG.ADD_TAG.id).to_string() == html
        assert ActivityLog.objects.filter(
            action=amo.LOG.ADD_TAG.id).count() == count + 1

    def test_edit_denied_tag(self):
        Tag.objects.get_or_create(tag_text='blue', denied=True)
        data = self.get_dict(tags='blue')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        error = 'Invalid tag: blue'
        self.assertFormError(response, 'form', 'tags', error)

    def test_edit_denied_tags_2(self):
        Tag.objects.get_or_create(tag_text='blue', denied=True)
        Tag.objects.get_or_create(tag_text='darn', denied=True)
        data = self.get_dict(tags='blue, darn, swearword')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        error = 'Invalid tags: blue, darn'
        self.assertFormError(response, 'form', 'tags', error)

    def test_edit_denied_tags_3(self):
        Tag.objects.get_or_create(tag_text='blue', denied=True)
        Tag.objects.get_or_create(tag_text='darn', denied=True)
        Tag.objects.get_or_create(tag_text='swearword', denied=True)
        data = self.get_dict(tags='blue, darn, swearword')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        error = 'Invalid tags: blue, darn, swearword'
        self.assertFormError(response, 'form', 'tags', error)

    def test_edit_remove_tag(self):
        self.tags.remove('tag2')

        count = ActivityLog.objects.all().count()
        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        result = pq(response.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))

        assert ActivityLog.objects.filter(
            action=amo.LOG.REMOVE_TAG.id).count() == count + 1

    def test_edit_minlength_tags(self):
        tags = self.tags
        tags.append('a' * (amo.MIN_TAG_LENGTH - 1))
        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200

        self.assertFormError(response, 'form', 'tags',
                             'All tags must be at least %d characters.' %
                             amo.MIN_TAG_LENGTH)

    def test_edit_max_tags(self):
        tags = self.tags

        for i in range(amo.MAX_TAGS + 1):
            tags.append('test%d' % i)

        data = self.get_dict()
        response = self.client.post(self.basic_edit_url, data)
        self.assertFormError(
            response, 'form', 'tags',
            'You have %d too many tags.' % (len(tags) - amo.MAX_TAGS))

    def test_edit_tag_empty_after_slug(self):
        start = Tag.objects.all().count()
        data = self.get_dict(tags='>>')
        self.client.post(self.basic_edit_url, data)

        # Check that the tag did not get created.
        assert start == Tag.objects.all().count()

    def test_edit_tag_slugified(self):
        data = self.get_dict(tags='<script>alert("foo")</script>')
        self.client.post(self.basic_edit_url, data)
        tag = Tag.objects.all().order_by('-pk')[0]
        assert tag.tag_text == 'scriptalertfooscript'

    def test_edit_restricted_tags(self):
        addon = self.get_addon()
        tag = Tag.objects.create(
            tag_text='i_am_a_restricted_tag', restricted=True)
        AddonTag.objects.create(tag=tag, addon=addon)

        res = self.client.get(self.basic_edit_url)
        divs = pq(res.content)('#addon_tags_edit .edit-addon-details')
        assert len(divs) == 2
        assert 'i_am_a_restricted_tag' in divs.eq(1).text()


class ContributionsTestsMixin(object):
    def test_contributions_url_not_url(self):
        data = self.get_dict(name='blah', slug='test_addon',
                             contributions='foooo')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'contributions', 'Enter a valid URL.')

    def test_contributions_url_not_valid_domain(self):
        data = self.get_dict(name='blah', slug='test_addon',
                             contributions='http://foo.baa/')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'form', 'contributions',
            'URL domain must be one of [%s], or a subdomain.' %
            ', '.join(amo.VALID_CONTRIBUTION_DOMAINS))

    def test_contributions_url_valid_domain(self):
        assert 'paypal.me' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(name='blah', slug='test_addon',
                             contributions='http://paypal.me/')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        assert self.addon.reload().contributions == 'http://paypal.me/'

    def test_contributions_url_valid_domain_sub(self):
        assert 'paypal.me' in amo.VALID_CONTRIBUTION_DOMAINS
        assert 'sub,paypal.me' not in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(name='blah', slug='test_addon',
                             contributions='http://sub.paypal.me/random/?path')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        assert self.addon.reload().contributions == (
            'http://sub.paypal.me/random/?path')


class L10nTestsMixin(object):
    def get_l10n_urls(self):
        paths = ('devhub.addons.edit', 'devhub.addons.owner')
        return [reverse(p, args=['a3615']) for p in paths]

    def test_l10n(self):
        Addon.objects.get(id=3615).update(default_locale='en-US')
        for url in self.get_l10n_urls():
            response = self.client.get(url)
            assert pq(
                response.content)('#l10n-menu').attr('data-default') == 'en-us'

    def test_l10n_not_us(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            response = self.client.get(url)
            assert pq(
                response.content)('#l10n-menu').attr('data-default') == 'fr'

    def test_l10n_not_us_id_url(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            url = '/id' + url[6:]
            response = self.client.get(url)
            assert pq(
                response.content)('#l10n-menu').attr('data-default') == 'fr'


class TestEditBasicListed(BaseTestEditBasic, TagTestsMixin,
                          ContributionsTestsMixin, L10nTestsMixin):
    __test__ = True

    def test_edit_categories_add(self):
        assert [c.id for c in self.get_addon().all_categories] == [22]
        self.cat_initial['categories'] = [22, 1]

        self.client.post(self.basic_edit_url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [1, 22]

    def test_edit_categories_add_featured(self):
        """Ensure that categories cannot be changed for featured add-ons."""
        self._feature_addon()

        self.cat_initial['categories'] = [22, 1]
        response = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)

        assert response.context['cat_form'].errors[0]['categories'] == (
            ['Categories cannot be changed while your add-on is featured for '
             'this application.'])
        # This add-on's categories should not change.
        assert sorted(addon_cats) == [22]

    def test_edit_categories_add_new_creatured_admin(self):
        """Ensure that admins can change categories for creatured add-ons."""
        assert self.client.login(email='admin@mozilla.com')
        self._feature_addon()
        response = self.client.get(self.basic_edit_url)
        doc = pq(response.content)
        assert doc('#addon-categories-edit div.addon-app-cats').length == 1
        assert doc('#addon-categories-edit > p').length == 0
        self.cat_initial['categories'] = [22, 1]
        response = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert 'categories' not in response.context['cat_form'].errors[0]
        # This add-on's categories should change.
        assert sorted(addon_cats) == [1, 22]

    def test_edit_categories_disable_creatured(self):
        """Ensure that other forms are okay when disabling category changes."""
        self._feature_addon()
        self.cat_initial['categories'] = [22, 1]
        data = self.get_dict()
        self.client.post(self.basic_edit_url, data)
        assert unicode(self.get_addon().name) == data['name']

    def test_edit_categories_no_disclaimer(self):
        """Ensure that there is a not disclaimer for non-creatured add-ons."""
        response = self.client.get(self.basic_edit_url)
        doc = pq(response.content)
        assert doc('#addon-categories-edit div.addon-app-cats').length == 1
        assert doc('#addon-categories-edit > p').length == 0

    def test_edit_no_previous_categories(self):
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(self.basic_edit_url)
        assert response.status_code == 200

        self.cat_initial['categories'] = [22, 71]
        response = self.client.post(self.basic_edit_url, self.get_dict())
        self.addon = self.get_addon()
        addon_cats = self.addon.categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22, 71]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert set(response.context['addon'].all_categories) == set(
            self.addon.all_categories)

    def test_edit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=1).save()
        assert sorted(
            [c.id for c in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22, 71]
        response = self.client.post(self.basic_edit_url, self.get_dict())
        self.addon = self.get_addon()
        addon_cats = self.addon.categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22, 71]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert set(response.context['addon'].all_categories) == set(
            self.addon.all_categories)

    def test_edit_categories_xss(self):
        category = Category.objects.get(id=22)
        category.db_name = '<script>alert("test");</script>'
        category.slug = 'xssattempt'
        category.save()

        self.cat_initial['categories'] = [22, 71]
        response = self.client.post(
            self.basic_edit_url, formset(self.cat_initial, initial_count=1))

        assert '<script>alert' not in response.content
        assert '&lt;script&gt;alert' in response.content

    def test_edit_categories_remove(self):
        category = Category.objects.get(id=1)
        AddonCategory(addon=self.addon, category=category).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22]
        response = self.client.post(self.basic_edit_url, self.get_dict())

        self.addon = self.get_addon()
        addon_cats = self.addon.categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [22]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert set(response.context['addon'].all_categories) == set(
            self.addon.all_categories)

    def test_edit_categories_required(self):
        del self.cat_initial['categories']
        response = self.client.post(
            self.basic_edit_url, formset(self.cat_initial, initial_count=1))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['This field is required.'])

    def test_edit_categories_max(self):
        assert amo.MAX_CATEGORIES == 2
        self.cat_initial['categories'] = [22, 1, 71]
        response = self.client.post(
            self.basic_edit_url, formset(self.cat_initial, initial_count=1))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['You can have only 2 categories.'])

    def test_edit_categories_other_failure(self):
        Category.objects.get(id=22).update(misc=True)
        self.cat_initial['categories'] = [22, 1]
        response = self.client.post(
            self.basic_edit_url, formset(self.cat_initial, initial_count=1))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['The miscellaneous category cannot be combined with additional '
             'categories.'])

    def test_edit_categories_nonexistent(self):
        self.cat_initial['categories'] = [100]
        response = self.client.post(
            self.basic_edit_url, formset(self.cat_initial, initial_count=1))
        assert response.context['cat_form'].errors[0]['categories'] == (
            ['Select a valid choice. 100 is not one of the available '
             'choices.'])

    def test_text_not_none_when_has_flags(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#addon-flags').text() == (
            'This add-on requires external software.')

    def test_text_none_when_no_flags(self):
        addon = self.get_addon()
        addon.update(external_software=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#addon-flags').text() == 'None'

    def test_nav_links_admin(self):
        assert self.client.login(email='admin@mozilla.com')
        response = self.client.get(self.url)
        doc = pq(response.content)('#edit-addon-nav')
        links = doc('ul:last').find('li a')
        assert links.eq(1).attr('href') == reverse(
            'reviewers.review', args=[self.addon.slug])
        assert links.eq(2).attr('href') == reverse(
            'reviewers.review', args=['unlisted', self.addon.slug])
        assert links.eq(3).attr('href') == reverse(
            'zadmin.addon_manage', args=[self.addon.slug])

    def test_not_experimental_flag(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#experimental-edit').text() == (
            'This add-on is ready for general use.')

    def test_experimental_flag(self):
        self.get_addon().update(is_experimental=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#experimental-edit').text() == (
            'This add-on is experimental.')

    def test_not_requires_payment_flag(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#requires-payment-edit').text() == (
            'This add-on doesn\'t require any additional payments, '
            'paid services or software, or additional hardware.')

    def test_requires_payment_flag(self):
        self.get_addon().update(requires_payment=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#requires-payment-edit').text() == (
            'This add-on requires payment, non-free services or '
            'software, or additional hardware.')


class TestEditMedia(BaseTestEdit):
    __test__ = True

    def setUp(self):
        super(TestEditMedia, self).setUp()
        self.media_edit_url = self.get_url('media', True)
        self.icon_upload = reverse('devhub.addons.upload_icon',
                                   args=[self.addon.slug])
        self.preview_upload = reverse('devhub.addons.upload_preview',
                                      args=[self.addon.slug])

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.media_edit_url).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form()], **kw)
        return {k: '' if v is None else v for k, v in fs.items()}

    def test_icon_upload_attributes(self):
        doc = pq(self.client.get(self.media_edit_url).content)
        field = doc('input[name=icon_upload]')
        assert field.length == 1
        assert sorted(field.attr('data-allowed-types').split('|')) == (
            ['image/jpeg', 'image/png'])
        assert field.attr('data-upload-url') == self.icon_upload

    def test_edit_media_defaulticon(self):
        data = {'icon_type': ''}
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_media_shows_proper_labels(self):
        """Regression test for

        https://github.com/mozilla/addons-server/issues/8900"""
        doc = pq(self.client.get(self.media_edit_url).content)

        labels = doc('#icons_default li label')

        assert labels.length == 18

        # First one is the default icon
        assert labels[0].get('for') == 'id_icon_type_2_2'
        assert labels[0].find('input').get('name') == 'icon_type'
        assert labels[0].find('input').get('value') == ''

        # Second one is a regular icon
        assert labels[1].get('for') == 'id_icon_type_3_3'
        assert labels[1].find('input').get('name') == 'icon_type'
        assert labels[1].find('input').get('value') == 'icon/alerts'

        # Make sure we're rendering our <input> fields for custom icon
        # upload correctly.
        # They're split into two fields which happens in
        # :func:`addons.forms:icons`
        inputs = doc('#icons_default li.hide input')

        assert inputs.length == 2
        assert inputs[0].get('name') == 'icon_type'
        assert inputs[0].get('value') == 'image/jpeg'

        assert inputs[1].get('name') == 'icon_type'
        assert inputs[1].get('value') == 'image/png'

    def test_edit_media_preuploadedicon(self):
        data = {'icon_type': 'icon/appearance'}
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/appearance-64.png')

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_media_uploadedicon(self):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = {
            'icon_type': 'image/png',
            'icon_upload_hash': response_json['upload_hash']
        }
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        url = addon.get_icon_url(64)
        assert ('addon_icons/3/%s' % addon.id) in url, (
            'Unexpected path: %r' % url)

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(user_media_path('addon_icons'),
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert storage.exists(dest)

        assert image_size(dest) == (32, 12)

        assert addon.icon_type == 'image/png'
        assert addon.icon_hash == 'bb362450'

    def test_edit_media_icon_log(self):
        self.test_edit_media_uploadedicon()
        log = ActivityLog.objects.all()
        assert log.count() == 1
        assert log[0].action == amo.LOG.CHANGE_ICON.id

    def test_edit_media_uploadedicon_noresize(self):
        img = "static/img/notifications/error.png"
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = {
            'icon_type': 'image/png',
            'icon_upload_hash': response_json['upload_hash']
        }
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        addon_url = addon.get_icon_url(64).split('?')[0]
        assert addon_url.endswith('addon_icons/3/%s-64.png' % addon.id), (
            'Unexpected path: %r' % addon_url)

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(user_media_path('addon_icons'),
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert storage.exists(dest)

        assert image_size(dest) == (48, 48)

        assert addon.icon_type == 'image/png'
        assert addon.icon_hash == 'f02063c9'

    def check_image_type(self, url, msg):
        img = 'static/js/zamboni/devhub.js'
        src_image = open(img, 'rb')

        res = self.client.post(url, {'upload_image': src_image})
        response_json = json.loads(res.content)
        assert response_json['errors'][0] == msg

    def test_edit_media_icon_wrong_type(self):
        self.check_image_type(self.icon_upload,
                              'Icons must be either PNG or JPG.')

    def test_edit_media_screenshot_wrong_type(self):
        self.check_image_type(self.preview_upload,
                              'Images must be either PNG or JPG.')

    def setup_image_status(self):
        addon = self.get_addon()
        self.icon_dest = os.path.join(addon.get_icon_dir(),
                                      '%s-32.png' % addon.id)
        os.makedirs(os.path.dirname(self.icon_dest))
        with storage.open(self.icon_dest, 'w') as f:
            f.write('some icon data\n')

        self.preview = addon.previews.create()
        self.preview.save()
        os.makedirs(os.path.dirname(self.preview.thumbnail_path))
        with storage.open(self.preview.thumbnail_path, 'w') as f:
            f.write('some icon data\n')
        self.url = reverse('devhub.ajax.image.status', args=[addon.slug])

    def test_image_status_no_choice(self):
        addon = self.get_addon()
        addon.update(icon_type='')
        url = reverse('devhub.ajax.image.status', args=[addon.slug])
        result = json.loads(self.client.get(url).content)
        assert result['icons']

    def test_image_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_fails(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        result = json.loads(self.client.get(self.url).content)
        assert not result['icons']

    def test_preview_status_works(self):
        self.setup_image_status()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

        # No previews means that all the images are done.
        self.addon.previews.all().delete()
        result = json.loads(self.client.get(self.url).content)
        assert result['previews']

    def test_preview_status_fails(self):
        self.setup_image_status()
        storage.delete(self.preview.thumbnail_path)
        result = json.loads(self.client.get(self.url).content)
        assert not result['previews']

    def test_image_status_persona(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        self.get_addon().update(type=amo.ADDON_PERSONA)
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def test_image_status_default(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        self.get_addon().update(icon_type='icon/photos')
        result = json.loads(self.client.get(self.url).content)
        assert result['icons']

    def check_image_animated(self, url, msg):
        filehandle = open(get_image_path('animated.png'), 'rb')

        res = self.client.post(url, {'upload_image': filehandle})
        response_json = json.loads(res.content)
        assert response_json['errors'][0] == msg

    def test_icon_animated(self):
        self.check_image_animated(self.icon_upload,
                                  'Icons cannot be animated.')

    def test_screenshot_animated(self):
        self.check_image_animated(self.preview_upload,
                                  'Images cannot be animated.')

    def preview_add(self, amount=1):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}
        data_formset = self.formset_media(**data)
        url = self.preview_upload
        response = self.client.post(url, data_formset)

        details = json.loads(response.content)
        upload_hash = details['upload_hash']

        # Create and post with the formset.
        fields = []
        for i in range(amount):
            fields.append(self.formset_new_form(caption='hi',
                                                upload_hash=upload_hash,
                                                position=i))
        data_formset = self.formset_media(*fields)
        self.client.post(self.media_edit_url, data_formset)

    def test_edit_media_preview_add(self):
        self.preview_add()

        assert str(self.get_addon().previews.all()[0].caption) == 'hi'

    def test_edit_media_preview_edit(self):
        self.preview_add()
        preview = self.get_addon().previews.all()[0]
        edited = {'caption': 'bye',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': preview.position,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.media_edit_url, data_formset)

        assert str(self.get_addon().previews.all()[0].caption) == 'bye'
        assert len(self.get_addon().previews.all()) == 1

    def test_edit_media_preview_reorder(self):
        self.preview_add(3)

        previews = self.get_addon().previews.all()

        base = {'upload_hash': '', 'file_upload': None}

        # Three preview forms were generated; mix them up here.
        one = {'caption': 'first', 'position': 1, 'id': previews[2].id}
        two = {'caption': 'second', 'position': 2, 'id': previews[0].id}
        three = {'caption': 'third', 'position': 3, 'id': previews[1].id}
        one.update(base)
        two.update(base)
        three.update(base)

        # Add them in backwards ("third", "second", "first")
        data_formset = self.formset_media(three, two, one, initial_count=3)
        assert data_formset['files-0-caption'] == 'third'
        assert data_formset['files-1-caption'] == 'second'
        assert data_formset['files-2-caption'] == 'first'

        self.client.post(self.media_edit_url, data_formset)
        # They should come out "first", "second", "third"
        assert str(self.get_addon().previews.all()[0].caption) == 'first'
        assert str(self.get_addon().previews.all()[1].caption) == 'second'
        assert str(self.get_addon().previews.all()[2].caption) == 'third'

    def test_edit_media_preview_delete(self):
        self.preview_add()
        preview = self.get_addon().previews.get()
        edited = {'DELETE': 'checked',
                  'upload_hash': '',
                  'id': preview.id,
                  'position': 0,
                  'file_upload': None}

        data_formset = self.formset_media(edited, initial_count=1)

        self.client.post(self.media_edit_url, data_formset)

        assert len(self.get_addon().previews.all()) == 0

    def test_edit_media_preview_add_another(self):
        self.preview_add()
        self.preview_add()

        assert len(self.get_addon().previews.all()) == 2

    def test_edit_media_preview_add_two(self):
        self.preview_add(2)

        assert len(self.get_addon().previews.all()) == 2


class BaseTestEditDetails(BaseTestEdit):
    __test__ = True

    def setUp(self):
        super(BaseTestEditDetails, self).setUp()
        self.details_url = self.get_url('details')
        self.details_edit_url = self.get_url('details', edit=True)

    def test_edit(self):
        data = {
            'description': 'New description with <em>html</em>!',
            'default_locale': 'en-US',
            'homepage': 'http://twitter.com/fligtarsmom'
        }

        response = self.client.post(self.details_edit_url, data)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_xss(self):
        """
        Let's try to put xss in our description, and safe html, and verify
        that we are playing safe.
        """
        self.addon.description = ("This\n<b>IS</b>"
                                  "<script>alert('awesome')</script>")
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert doc('#edit-addon-details span[lang]').html() == (
            "This<br/><b>IS</b>&lt;script&gt;alert('awesome')&lt;/script&gt;")

    def test_edit_homepage_optional(self):
        data = {
            'description': 'New description with <em>html</em>!',
            'default_locale': 'en-US',
            'homepage': ''
        }

        response = self.client.post(self.details_edit_url, data)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]


class TestEditDetailsListed(BaseTestEditDetails):

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        description, homepage = map(unicode, [self.addon.description,
                                              self.addon.homepage])
        # TODO: description should get fixed up with the form.
        error = ('Before changing your default locale you must have a name, '
                 'summary, and description in that locale. '
                 'You are missing ')

        data = {
            'description': description,
            'homepage': homepage,
            'default_locale': 'fr'
        }
        response = self.client.post(self.details_edit_url, data)
        # We can't use assertFormError here, because the missing fields are
        # stored in a dict, which isn't ordered.
        form_error = response.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'name'" in form_error
        assert "'summary'" in form_error

        # Now we have a name.
        self.addon.name = {'fr': 'fr name'}
        self.addon.save()
        response = self.client.post(self.details_edit_url, data)
        form_error = response.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'summary'" in form_error

        # Now we have a summary.
        self.addon.summary = {'fr': 'fr summary'}
        self.addon.save()
        response = self.client.post(self.details_edit_url, data)
        form_error = response.context['form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error

        # Now we're sending an fr description with the form.
        data['description_fr'] = 'fr description'
        response = self.client.post(self.details_edit_url, data)
        assert response.context['form'].errors == {}

    def test_edit_default_locale_frontend_error(self):
        data = {
            'description': 'xx',
            'homepage': 'https://staticfil.es/',
            'default_locale': 'fr'
        }
        response = self.client.post(self.details_edit_url, data)
        self.assertContains(
            response, 'Before changing your default locale you must')

    def test_edit_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')
        response = self.client.get(self.details_url)
        assert pq(response.content)('.addon_edit_locale').eq(0).text() == (
            'English (US)')


class TestEditSupport(BaseTestEdit):
    __test__ = True

    def setUp(self):
        super(TestEditSupport, self).setUp()
        self.support_url = self.get_url('support')
        self.support_edit_url = self.get_url('support', edit=True)

    def test_edit_support(self):
        data = {
            'support_email': 'sjobs@apple.com',
            'support_url': 'http://apple.com/'
        }

        response = self.client.post(self.support_edit_url, data)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_support_optional_url(self):
        data = {
            'support_email': 'sjobs@apple.com',
            'support_url': ''
        }

        response = self.client.post(self.support_edit_url, data)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]

    def test_edit_support_optional_email(self):
        data = {
            'support_email': '',
            'support_url': 'http://apple.com/'
        }

        response = self.client.post(self.support_edit_url, data)
        assert response.context['form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert unicode(getattr(addon, k)) == data[k]


class TestEditTechnical(BaseTestEdit):
    __test__ = True
    fixtures = BaseTestEdit.fixtures + [
        'addons/persona', 'base/addon_40', 'base/addon_1833_yoono',
        'base/addon_4664_twitterbar.json',
        'base/addon_5299_gcal', 'base/addon_6113']

    def setUp(self):
        super(TestEditTechnical, self).setUp()
        self.dependent_addon = Addon.objects.get(id=5579)
        AddonDependency.objects.create(addon=self.addon,
                                       dependent_addon=self.dependent_addon)
        self.technical_url = self.get_url('technical')
        self.technical_edit_url = self.get_url('technical', edit=True)
        ctx = self.client.get(self.technical_edit_url).context
        self.dep = initial(ctx['dependency_form'].initial_forms[0])
        self.dep_initial = formset(self.dep, prefix='dependencies',
                                   initial_count=1)

    def dep_formset(self, *args, **kw):
        kw.setdefault('initial_count', 1)
        kw.setdefault('prefix', 'dependencies')
        return formset(self.dep, *args, **kw)

    def formset(self, data):
        return self.dep_formset(**data)

    def test_log(self):
        data = self.formset({'developer_comments': 'This is a test'})
        assert ActivityLog.objects.count() == 0
        response = self.client.post(self.technical_edit_url, data)
        assert response.context['form'].errors == {}
        assert ActivityLog.objects.filter(
            action=amo.LOG.EDIT_PROPERTIES.id).count() == 1

    def test_technical_on(self):
        # Turn everything on
        data = {
            'developer_comments': 'Test comment!',
            'external_software': 'on',
            'view_source': 'on',
            'whiteboard-public': 'Whiteboard info.'
        }

        response = self.client.post(
            self.technical_edit_url, self.formset(data))
        assert response.context['form'].errors == {}

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                assert unicode(getattr(addon, k)) == unicode(data[k])
            elif k == 'whiteboard-public':
                assert unicode(addon.whiteboard.public) == unicode(data[k])
            else:
                assert getattr(addon, k) == (data[k] == 'on')

        # Andddd offf
        data = {'developer_comments': 'Test comment!'}
        response = self.client.post(
            self.technical_edit_url, self.formset(data))
        addon = self.get_addon()

        assert not addon.external_software
        assert not addon.view_source

    def test_technical_devcomment_notrequired(self):
        data = {
            'developer_comments': '',
            'external_software': 'on',
            'view_source': 'on'
        }
        response = self.client.post(
            self.technical_edit_url, self.formset(data))
        assert response.context['form'].errors == {}

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                assert unicode(getattr(addon, k)) == unicode(data[k])
            else:
                assert getattr(addon, k) == (data[k] == 'on')

    def test_auto_repackage_not_shown(self):
        file_ = self.addon.current_version.all_files[0]
        file_.jetpack_version = None
        file_.save()
        response = self.client.get(self.technical_edit_url)
        self.assertNotContains(response, 'Upgrade SDK?')

    def test_auto_repackage_shown(self):
        file_ = self.addon.current_version.all_files[0]
        file_.jetpack_version = '1.0'
        file_.save()
        response = self.client.get(self.technical_edit_url)
        self.assertContains(response, 'Upgrade SDK?')

    def test_dependencies_none(self):
        AddonDependency.objects.all().delete()
        assert list(self.addon.all_dependencies) == []
        response = self.client.get(self.technical_url)
        assert pq(response.content)('#required-addons .empty').length == 1

    def test_dependencies_overview(self):
        assert [d.id for d in self.addon.all_dependencies] == [5579]
        response = self.client.get(self.technical_url)
        req = pq(response.content)('#required-addons')
        assert req.length == 1
        assert req.attr('data-src') == (
            reverse('devhub.ajax.dependencies', args=[self.addon.slug]))
        assert req.find('li').length == 1
        link = req.find('a')
        assert link.attr('href') == self.dependent_addon.get_url_path()
        assert link.text() == unicode(self.dependent_addon.name)

    def test_dependencies_initial(self):
        response = self.client.get(self.technical_edit_url)
        form = pq(response.content)(
            '#required-addons .dependencies li[data-addonid]')
        assert form.length == 1
        assert form.find('input[id$=-dependent_addon]').val() == (
            str(self.dependent_addon.id))
        div = form.find('div')
        assert div.attr('style') == (
            'background-image:url(%s)' % self.dependent_addon.icon_url)
        link = div.find('a')
        assert link.attr('href') == self.dependent_addon.get_url_path()
        assert link.text() == unicode(self.dependent_addon.name)

    def test_dependencies_add(self):
        addon = Addon.objects.get(id=5299)
        assert addon.type == amo.ADDON_EXTENSION
        assert addon in list(Addon.objects.public())

        data = self.dep_formset({'dependent_addon': addon.id})
        response = self.client.post(self.technical_edit_url, data)
        assert not any(response.context['dependency_form'].errors)
        self.check_dep_ids([self.dependent_addon.id, addon.id])

        response = self.client.get(self.technical_edit_url)
        reqs = pq(response.content)('#required-addons .dependencies')
        assert reqs.find('li[data-addonid]').length == 2
        req = reqs.find('li[data-addonid="5299"]')
        assert req.length == 1
        link = req.find('div a')
        assert link.attr('href') == addon.get_url_path()
        assert link.text() == unicode(addon.name)

    def test_dependencies_limit(self):
        deps = Addon.objects.public().exclude(
            Q(id__in=[self.addon.id, self.dependent_addon.id]) |
            Q(type=amo.ADDON_PERSONA))
        args = []
        assert deps.count() > 3  # The limit is 3.
        for dep in deps:
            args.append({'dependent_addon': dep.id})
        data = self.dep_formset(*args)
        response = self.client.post(self.technical_edit_url, data)
        assert response.context['dependency_form'].non_form_errors() == (
            ['There cannot be more than 3 required add-ons.'])

    def test_dependencies_limit_with_deleted_form(self):
        deps = Addon.objects.public().exclude(
            Q(id__in=[self.addon.id, self.dependent_addon.id]) |
            Q(type=amo.ADDON_PERSONA))[:3]
        args = []
        for dep in deps:
            args.append({'dependent_addon': dep.id})

        # If we delete one form and add three, everything should be A-OK.
        self.dep['DELETE'] = True
        data = self.dep_formset(*args)
        response = self.client.post(self.technical_edit_url, data)
        assert not any(response.context['dependency_form'].errors)
        self.check_dep_ids(deps.values_list('id', flat=True))

    def check_dep_ids(self, expected=None):
        if expected is None:
            expected = []
        ids = AddonDependency.objects.values_list(
            'dependent_addon__id', flat=True)
        assert sorted(list(ids)) == sorted(expected)

    def check_bad_dep(self, r):
        """This helper checks that bad dependency data doesn't go through."""
        assert r.context['dependency_form'].errors[1]['dependent_addon'] == (
            ['Select a valid choice. That choice is not one of the available '
             'choices.'])
        self.check_dep_ids([self.dependent_addon.id])

    def test_dependencies_add_reviewed(self):
        """Ensure that reviewed add-ons can be made as dependencies."""
        addon = Addon.objects.get(id=40)
        for status in amo.REVIEWED_STATUSES:
            addon.update(status=status)

            assert addon in list(Addon.objects.public())
            data = self.dep_formset({'dependent_addon': addon.id})
            response = self.client.post(self.technical_edit_url, data)
            assert not any(response.context['dependency_form'].errors)
            self.check_dep_ids([self.dependent_addon.id, addon.id])

            AddonDependency.objects.get(dependent_addon=addon).delete()

    def test_dependencies_no_add_unreviewed(self):
        """Ensure that unreviewed add-ons cannot be made as dependencies."""
        addon = Addon.objects.get(id=40)
        for status in amo.UNREVIEWED_ADDON_STATUSES:
            addon.update(status=status)

            assert addon not in list(Addon.objects.public())
            data = self.dep_formset({'dependent_addon': addon.id})
            response = self.client.post(self.technical_edit_url, data)
            self.check_bad_dep(response)

    def test_dependencies_no_add_reviewed_persona(self):
        """Ensure that reviewed Personas cannot be made as dependencies."""
        addon = Addon.objects.get(id=15663)
        assert addon.type == amo.ADDON_PERSONA
        assert addon in list(Addon.objects.public())
        data = self.dep_formset({'dependent_addon': addon.id})
        response = self.client.post(self.technical_edit_url, data)
        self.check_bad_dep(response)

    def test_dependencies_no_add_unreviewed_persona(self):
        """Ensure that unreviewed Personas cannot be made as dependencies."""
        addon = Addon.objects.get(id=15663)
        addon.update(status=amo.STATUS_PENDING)
        assert addon.status == amo.STATUS_PENDING
        assert addon not in list(Addon.objects.public())
        data = self.dep_formset({'dependent_addon': addon.id})
        response = self.client.post(self.technical_edit_url, data)
        self.check_bad_dep(response)

    def test_dependencies_add_self(self):
        """Ensure that an add-on cannot be made dependent on itself."""
        data = self.dep_formset({'dependent_addon': self.addon.id})
        response = self.client.post(self.technical_edit_url, data)
        self.check_bad_dep(response)

    def test_dependencies_add_invalid(self):
        """Ensure that a non-existent add-on cannot be a dependency."""
        data = self.dep_formset({'dependent_addon': 9999})
        response = self.client.post(self.technical_edit_url, data)
        self.check_bad_dep(response)

    def test_dependencies_add_duplicate(self):
        """Ensure that an add-on cannot be made dependent more than once."""
        data = self.dep_formset({'dependent_addon': self.dependent_addon.id})
        response = self.client.post(self.technical_edit_url, data)
        assert (
            response.context['dependency_form'].forms[1].non_field_errors() ==
            ['Addon dependency with this Addon and Dependent addon already '
             'exists.'])
        self.check_dep_ids([self.dependent_addon.id])

    def test_dependencies_delete(self):
        self.dep['DELETE'] = True
        data = self.dep_formset(total_count=1, initial_count=1)
        response = self.client.post(self.technical_edit_url, data)
        assert not any(response.context['dependency_form'].errors)
        self.check_dep_ids()

    def test_dependencies_add_delete(self):
        """Ensure that we can both delete a dependency and add another."""
        self.dep['DELETE'] = True
        data = self.dep_formset({'dependent_addon': 5299})
        response = self.client.post(self.technical_edit_url, data)
        assert not any(response.context['dependency_form'].errors)
        self.check_dep_ids([5299])


class TestEditBasicUnlisted(BaseTestEditBasic, L10nTestsMixin):
    listed = False
    __test__ = True


class TestEditDetailsUnlisted(BaseTestEditDetails):
    listed = False


class TestEditTechnicalUnlisted(BaseTestEdit):
    __test__ = True
    listed = False

    def test_whiteboard(self):
        edit_url = self.get_url('technical', edit=True)

        # It's okay to post empty whiteboard instructions.
        response = self.client.post(edit_url, {'whiteboard-public': ''})
        assert response.context['form'].errors == {}

        # Let's update it.
        response = self.client.post(
            edit_url, {'whiteboard-public': 'important stuff'})
        assert response.context['form'].errors == {}
        addon = self.get_addon()
        assert addon.whiteboard.public == 'important stuff'

        # And clear it again.
        response = self.client.post(edit_url, {'whiteboard-public': ''})
        assert response.context['form'].errors == {}
        addon = self.get_addon()
        assert addon.whiteboard.public == ''


class StaticMixin(object):
    def setUp(self):
        super(StaticMixin, self).setUp()
        addon = self.get_addon()
        addon.update(type=amo.ADDON_STATICTHEME)
        if self.listed:
            AddonCategory.objects.filter(addon=addon).delete()
            Category.from_static_category(CATEGORIES_BY_ID[300], save=True)
            Category.from_static_category(CATEGORIES_BY_ID[308], save=True)
            VersionPreview.objects.create(version=addon.current_version)


class TestEditBasicStaticThemeListed(StaticMixin, BaseTestEditBasic,
                                     TagTestsMixin, ContributionsTestsMixin,
                                     L10nTestsMixin):
    __test__ = True

    def get_dict(self, **kw):
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary', 'category': 300,
                  'tags': ', '.join(self.tags)}
        result.update(**kw)
        return result

    def test_edit_categories_set(self):
        assert [cat.id for cat in self.get_addon().all_categories] == []
        response = self.client.post(
            self.basic_edit_url, self.get_dict(category=308))
        assert set(response.context['addon'].all_categories) == set(
            self.get_addon().all_categories)

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [308]

    def test_edit_categories_change(self):
        category = Category.objects.get(id=300)
        AddonCategory(addon=self.addon, category=category).save()
        assert sorted(
            [cat.id for cat in self.get_addon().all_categories]) == [300]

        self.client.post(self.basic_edit_url, self.get_dict(category=308))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        # Only ever one category for Static Themes
        assert category_ids_new == [308]
        # Check we didn't delete the Category object too!
        assert category.reload()

    def test_edit_categories_required(self):
        data = self.get_dict(category='')
        response = self.client.post(self.basic_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'cat_form', 'category', 'This field is required.')

    def test_edit_categories_add_featured(self):
        """Ensure that categories cannot be changed for featured add-ons."""
        category = Category.objects.get(id=308)
        AddonCategory(addon=self.addon, category=category).save()
        self._feature_addon(self.addon.id)

        response = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)

        # This add-on's categories should not change.
        assert sorted(addon_cats) == [308]
        self.assertFormError(
            response, 'cat_form', 'category',
            'Categories cannot be changed while your add-on is featured.')

    def test_edit_categories_add_new_creatured_admin(self):
        """Ensure that admins can change categories for creatured add-ons."""
        assert self.client.login(email='admin@mozilla.com')
        category = Category.objects.get(id=308)
        AddonCategory(addon=self.addon, category=category).save()
        self._feature_addon(self.addon.id)

        response = self.client.get(self.basic_edit_url)
        doc = pq(response.content)
        assert doc('#addon-categories-edit').length == 1
        assert doc('#addon-categories-edit > p').length == 0
        response = self.client.post(self.basic_edit_url, self.get_dict())
        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert 'category' not in response.context['cat_form'].errors
        # This add-on's categories should change.
        assert sorted(addon_cats) == [300]

    def test_edit_categories_disable_creatured(self):
        """Ensure that other forms are okay when disabling category changes."""
        self._feature_addon()
        data = self.get_dict()
        self.client.post(self.basic_edit_url, data)
        assert unicode(self.get_addon().name) == data['name']

    def test_theme_preview_shown(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert 'Preview' in doc('h3').text()
        assert doc('div.edit-addon-section img')[0].attrib['src'] == (
            self.addon.current_version.previews.first().image_url)
        assert len(doc('div.edit-addon-section img')) == 1  # Just one preview.


class TestEditBasicStaticThemeUnlisted(StaticMixin, TestEditBasicUnlisted):
    def get_dict(self, **kw):
        result = {'name': 'new name', 'slug': 'test_slug',
                  'summary': 'new summary'}
        result.update(**kw)
        return result

    def test_theme_preview_not_shown(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert 'Preview' not in doc('h3').text()


class TestEditDetailsStaticThemeListed(StaticMixin, TestEditDetailsListed):
    pass


class TestEditDetailsStaticThemeUnlisted(StaticMixin, TestEditDetailsUnlisted):
    pass


class TestEditTechnicalStaticThemeListed(StaticMixin,
                                         TestEditTechnicalUnlisted):
    # Using the Unlisted test case because it's got the right tests for us.
    listed = True


class TestEditTechnicalStaticThemeUnlisted(StaticMixin,
                                           TestEditTechnicalUnlisted):
    pass


class TestThemeEdit(TestCase):
    fixtures = ['base/user_999']

    def setUp(self):
        super(TestThemeEdit, self).setUp()
        self.addon = addon_factory(type=amo.ADDON_PERSONA)
        self.user = UserProfile.objects.get()
        self.addon.addonuser_set.create(user=self.user)

    @mock.patch('olympia.amo.messages.error')
    def test_desc_too_long_error(self, message_mock):
        data = {'description': 'a' * 501}
        req = req_factory_factory(
            self.addon.get_dev_url('edit'),
            user=self.user, post=True, data=data, session={})
        response = edit_theme(req, self.addon.slug)
        doc = pq(response.content)
        assert 'characters' in doc('#trans-description + ul li').text()

    def test_no_reupload_on_pending(self):
        self.addon.update(status=amo.STATUS_PENDING)
        req = req_factory_factory(
            self.addon.get_dev_url('edit'), user=self.user, session={})
        response = edit_theme(req, self.addon.slug)
        doc = pq(response.content)
        assert not doc('a.reupload')

        self.addon.update(status=amo.STATUS_PUBLIC)
        req = req_factory_factory(
            self.addon.get_dev_url('edit'), user=self.user, session={})
        response = edit_theme(req, self.addon.slug)
        doc = pq(response.content)
        assert doc('a.reupload')

    def test_color_input_is_empty_at_creation(self):
        self.client.login(email='regular@mozilla.com')
        response = self.client.get(reverse('devhub.themes.submit'))
        doc = pq(response.content)
        el = doc('input.color-picker')
        assert el.attr('type') == 'text'
        assert not el.attr('value')

    def test_color_input_is_not_empty_at_edit(self):
        color = "123456"
        self.addon.persona.accentcolor = color
        self.addon.persona.save()
        self.client.login(email='regular@mozilla.com')
        url = reverse('devhub.themes.edit', args=(self.addon.slug, ))
        response = self.client.get(url)
        doc = pq(response.content)
        el = doc('input#id_accentcolor')
        assert el.attr('type') == 'text'
        assert el.attr('value') == "#" + color
