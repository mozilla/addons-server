import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.encoding import force_str

from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonCategory
from olympia.amo.tests import (
    SQUOTE_ESCAPED,
    TestCase,
    addon_factory,
    formset,
    initial,
    user_factory,
)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import image_size
from olympia.constants.categories import CATEGORIES
from olympia.tags.models import AddonTag, Tag
from olympia.users.models import UserProfile
from olympia.versions.models import VersionPreview


class BaseTestEdit(TestCase):
    fixtures = [
        'base/users',
        'base/addon_3615',
        'base/addon_5579',
    ]
    listed = True
    __test__ = False  # this is an abstract test case

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))

        addon = self.get_addon()
        self.tags = ['tag3', 'tag2', 'tag1']
        for t in self.tags:
            Tag.objects.get_or_create(tag_text=t)[0].add_tag(addon)
        if self.listed:
            self.make_addon_listed(addon)
            ac = AddonCategory.objects.filter(addon=addon, category_id=22)[0]
            ac.save()
            AddonCategory.objects.filter(addon=addon, category_id__in=[1, 71]).delete()
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


class BaseTestEditDescribe(BaseTestEdit):
    __test__ = False  # this is an abstract test case

    def setUp(self):
        super().setUp()
        self.describe_edit_url = self.get_url('describe', edit=True)
        if self.listed:
            ctx = self.client.get(self.describe_edit_url).context
            self.cat_initial = initial(ctx['cat_form'])

    def get_dict(self, **kw):
        result = {
            'name': 'new name',
            'slug': 'test_slug',
            'summary': 'new summary',
            'description': 'new description',
        }
        if self.listed:
            result.update({'is_experimental': True, 'requires_payment': True})
            result.update(self.cat_initial)

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
        response = self.client.get('/en-US/developers/addon/3615/', follow=True)
        self.assert3xx(response, self.url, 301)

    def test_edit(self):
        old_name = self.addon.name
        data = self.get_dict()

        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        addon = self.get_addon()

        assert str(addon.name) == data['name']
        assert addon.name.id == old_name.id

        assert str(addon.summary) == data['summary']
        assert str(addon.slug) == data['slug']

        if self.listed:
            assert [str(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_slug_invalid(self):
        old_edit = self.describe_edit_url
        data = self.get_dict(name='', slug='invalid')
        response = self.client.post(self.describe_edit_url, data)
        doc = pq(response.content)
        assert doc('form').attr('action') == old_edit

    def test_edit_slug_valid(self):
        old_edit = self.describe_edit_url
        data = self.get_dict(slug='valid')
        response = self.client.post(self.describe_edit_url, data)
        doc = pq(response.content)
        assert doc('form').attr('action') != old_edit

        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.ADDON_SLUG_CHANGED.id
        assert activity_log.user == self.user
        assert activity_log.arguments == [self.addon, self.addon.slug, 'valid']
        assert f'slug from {self.addon.slug} to valid' in str(activity_log)

    def test_edit_as_developer(self):
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        data = self.get_dict()
        response = self.client.post(self.describe_edit_url, data)
        # Make sure we get errors when they are just regular users.
        assert response.status_code == 403 if self.listed else 404

        devuser = UserProfile.objects.get(pk=999)
        self.get_addon().addonuser_set.create(user=devuser, role=amo.AUTHOR_ROLE_DEV)
        response = self.client.post(self.describe_edit_url, data)

        assert response.status_code == 200
        addon = self.get_addon()

        assert str(addon.name) == data['name']
        assert str(addon.summary) == data['summary']
        assert str(addon.slug) == data['slug']

        if self.listed:
            assert [str(t) for t in addon.tags.all()] == sorted(self.tags)

    def test_edit_name_required(self):
        data = self.get_dict(name='', slug='test_addon')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'main_form', 'name', 'This field is required.')
        assert self.get_addon().name != ''

    def test_edit_name_spaces(self):
        data = self.get_dict(name='    ', slug='test_addon')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'main_form', 'name', 'This field is required.')

    def test_edit_name_symbols_only(self):
        data = self.get_dict(name='()+([#')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'main_form', 'name', error)

        data = self.get_dict(name='±↡∋⌚')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'main_form', 'name', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(name='ø')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        assert self.get_addon().name == 'ø'

    def test_edit_slugs_unique(self):
        Addon.objects.get(id=5579).update(slug='test_slug')
        data = self.get_dict()
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'slug',
            'This slug is already in use. Please choose another.',
        )

    def test_edit_name_not_empty(self):
        data = self.get_dict(name='', slug=self.addon.slug, summary=self.addon.summary)
        response = self.client.post(self.describe_edit_url, data)
        self.assertFormError(response, 'main_form', 'name', 'This field is required.')

    def test_edit_name_max_length(self):
        data = self.get_dict(
            name='xx' * 70, slug=self.addon.slug, summary=self.addon.summary
        )
        response = self.client.post(self.describe_edit_url, data)
        self.assertFormError(
            response,
            'main_form',
            'name',
            'Ensure this value has at most 50 characters (it has 140).',
        )

    def test_edit_summary_symbols_only(self):
        data = self.get_dict(summary='()+([#')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'main_form', 'summary', error)

        data = self.get_dict(summary='±↡∋⌚')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        error = 'Ensure this field contains at least one letter or number character.'
        self.assertFormError(response, 'main_form', 'summary', error)

        # 'ø' is not a symbol, it's actually a letter, so it should be valid.
        data = self.get_dict(summary='ø')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        assert self.get_addon().summary == 'ø'

    def test_edit_summary_max_length(self):
        data = self.get_dict(
            name=self.addon.name, slug=self.addon.slug, summary='x' * 251
        )
        response = self.client.post(self.describe_edit_url, data)
        self.assertFormError(
            response,
            'main_form',
            'summary',
            'Ensure this value has at most 250 characters (it has 251).',
        )

    def test_nav_links(self):
        if self.listed:
            links = [
                self.addon.get_dev_url('edit'),  # Edit Product Page
                self.addon.get_dev_url('owner'),  # Manage Authors
                self.addon.get_dev_url('versions'),  # Manage Status & Versions
                self.addon.get_url_path(),  # View Listing
                reverse('devhub.feed', args=[self.addon.slug]),  # View Recent
                reverse('stats.overview', args=[self.addon.slug]),  # Stats
            ]
        else:
            links = [
                self.addon.get_dev_url('edit'),  # Edit Product Page
                self.addon.get_dev_url('owner'),  # Manage Authors
                self.addon.get_dev_url('versions'),  # Manage Status & Versions
                reverse('devhub.feed', args=[self.addon.slug]),  # View Recent
                reverse('stats.overview', args=[self.addon.slug]),  # Stats
            ]

        response = self.client.get(self.url)
        doc_links = [
            str(a.attrib['href'])
            for a in pq(response.content)('#edit-addon-nav').find('li a')
        ]
        assert links == doc_links

    def test_nav_links_uri_match(self):
        self.get_addon().update(slug='모질라')

        response = self.client.get(self.get_addon().get_dev_url())
        selected_link = (
            pq(response.content)('#edit-addon-nav').find('li').hasClass('selected')
        )

        assert selected_link is True

    def test_metadata_change_triggers_content_review(self):
        data = self.get_dict()
        addon = self.addon = self.get_addon()
        AddonApprovalsCounter.approve_content_for_addon(addon=addon)
        old_content_review = AddonApprovalsCounter.objects.get(
            addon=addon
        ).last_content_review
        assert old_content_review

        # make the edit
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        addon = self.addon = self.get_addon()

        if self.listed:
            # last_content_review should have been reset
            assert not AddonApprovalsCounter.objects.get(
                addon=addon
            ).last_content_review
        else:
            # Do not reset last_content_review for unlisted-only add-ons
            assert (
                old_content_review
                == AddonApprovalsCounter.objects.get(addon=addon).last_content_review
            )
        # Check metadata is updated in any case
        assert str(addon.name) == data['name']
        assert str(addon.summary) == data['summary']

        # Now repeat, but we won't be changing either name or summary
        AddonApprovalsCounter.approve_content_for_addon(addon=addon)
        assert AddonApprovalsCounter.objects.get(addon=addon).last_content_review
        data['description'] = 'its a totally new description!'
        self.describe_edit_url = self.get_url('describe', edit=True)
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        addon = self.addon = self.get_addon()

        # Still keeps its date this time, so no new content review
        assert AddonApprovalsCounter.objects.get(addon=addon).last_content_review
        # And metadata was updated
        assert str(addon.description) == data['description']

        if self.listed:
            # Check this still works on an (old) addon without a content review
            AddonApprovalsCounter.objects.get(addon=addon).delete()
            data['summary'] = 'some change'
            self.describe_edit_url = self.get_url('describe', edit=True)
            response = self.client.post(self.describe_edit_url, data)
            assert response.status_code == 200
            addon = self.addon = self.get_addon()
            assert not AddonApprovalsCounter.objects.get(
                addon=addon
            ).last_content_review
            assert str(addon.summary) == data['summary']

    def test_edit_xss(self):
        """
        Let's try to put xss in our description, and safe html, and verify
        that we are playing safe.
        """
        self.addon.description = 'This\n<b>IS</b>' "<script>alert('awesome')</script>"
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        assert doc('#addon-description span[lang]').html() == (
            "This<br/><b>IS</b>&lt;script&gt;alert('awesome')&lt;/script&gt;"
        )

        response = self.client.get(self.describe_edit_url)
        assert response.status_code == 200

        assert b'<script>' not in response.content
        assert (
            f'This\n&lt;b&gt;IS&lt;/b&gt;&lt;script&gt;alert({SQUOTE_ESCAPED}awesome'
            f'{SQUOTE_ESCAPED})&lt;/script&gt;</textarea>'
        ) in response.content.decode('utf-8')

    def test_description_optional(self):
        """Description is optional by default - so confirm that here and
        selectively override in listed test sub classes.
        Will need re-working once `content-optimization` switch is removed."""
        addon = self.get_addon()
        addon.description = 'something!'
        addon.save()
        data = self.get_dict(description='')
        self.client.post(self.describe_edit_url, data)
        addon = self.get_addon()
        assert addon.description == ''

    def test_description_min_length_not_in_html_attrs(self):
        response = self.client.get(self.describe_edit_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#trans-description textarea').attr('minlength')

    @override_switch('content-optimization', active=False)
    def test_name_summary_lengths_short(self):
        # check the separate name and summary labels, etc are served
        response = self.client.get(self.url)
        assert b'Name and Summary' not in response.content
        assert b'It will be shown in listings and searches' in response.content

        self.client.post(self.describe_edit_url, self.get_dict(name='a', summary='b'))
        assert self.get_addon().name == 'a'
        assert self.get_addon().summary == 'b'

    @override_switch('content-optimization', active=False)
    def test_name_summary_lengths_long(self):
        self.client.post(
            self.describe_edit_url, self.get_dict(name='a' * 50, summary='b' * 50)
        )
        assert self.get_addon().name == 'a' * 50
        assert self.get_addon().summary == 'b' * 50

    @override_switch('content-optimization', active=True)
    def test_name_summary_lengths_content_optimization(self):
        # check the combined name and summary label, etc are served
        response = self.client.get(self.url)
        assert b'Name and Summary' in response.content

        # name and summary are too short
        response = self.client.post(
            self.describe_edit_url, self.get_dict(name='a', summary='b')
        )
        assert self.get_addon().name != 'a'
        assert self.get_addon().summary != 'b'
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'name',
            'Ensure this value has at least 2 characters (it has 1).',
        )
        self.assertFormError(
            response,
            'main_form',
            'summary',
            'Ensure this value has at least 2 characters (it has 1).',
        )

        # name and summary individually are okay, but together are too long
        response = self.client.post(
            self.describe_edit_url, self.get_dict(name='a' * 50, summary='b' * 50)
        )
        assert self.get_addon().name != 'a' * 50
        assert self.get_addon().summary != 'b' * 50
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'name',
            'Ensure name and summary combined are at most 70 characters '
            '(they have 100).',
        )

        # success: together name and summary are 70 characters.
        response = self.client.post(
            self.describe_edit_url, self.get_dict(name='a' * 2, summary='b' * 68)
        )
        assert self.get_addon().name == 'a' * 2
        assert self.get_addon().summary == 'b' * 68
        assert response.status_code == 200


class L10nTestsMixin:
    def get_l10n_urls(self):
        paths = ('devhub.addons.edit', 'devhub.addons.owner')
        return [reverse(p, args=['a3615']) for p in paths]

    def test_l10n(self):
        Addon.objects.get(id=3615).update(default_locale='en-US')
        for url in self.get_l10n_urls():
            response = self.client.get(url)
            assert pq(response.content)('#l10n-menu').attr('data-default') == 'en-us'

    def test_l10n_not_us(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            response = self.client.get(url)
            assert pq(response.content)('#l10n-menu').attr('data-default') == 'fr'

    def test_l10n_not_us_id_url(self):
        Addon.objects.get(id=3615).update(default_locale='fr')
        for url in self.get_l10n_urls():
            url = '/id' + url[6:]
            response = self.client.get(url)
            assert pq(response.content)('#l10n-menu').attr('data-default') == 'fr'


class TestEditDescribeListed(BaseTestEditDescribe, L10nTestsMixin):
    __test__ = True

    def test_edit_categories_add(self):
        assert [c.id for c in self.get_addon().all_categories] == [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        ]
        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ]

        self.client.post(self.describe_edit_url, self.get_dict())

        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

    def test_edit_no_previous_categories(self):
        AddonCategory.objects.filter(addon=self.addon).delete()
        response = self.client.get(self.describe_edit_url)
        assert response.status_code == 200

        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]
        response = self.client.post(self.describe_edit_url, self.get_dict())
        self.addon = self.get_addon()
        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert {cat.id for cat in response.context['addon'].all_categories} == {
            cat.id for cat in self.addon.all_categories
        }

    def test_edit_categories_addandremove(self):
        AddonCategory(
            addon=self.addon,
            category_id=CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ).save()
        assert sorted(c.id for c in self.get_addon().all_categories) == [
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]
        response = self.client.post(self.describe_edit_url, self.get_dict())
        self.addon = self.get_addon()
        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
        ]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert {cat.id for cat in response.context['addon'].all_categories} == {
            cat.id for cat in self.addon.all_categories
        }

    def test_edit_categories_remove(self):
        AddonCategory(addon=self.addon, category_id=1).save()
        assert sorted(cat.id for cat in self.get_addon().all_categories) == [
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
        ]

        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id
        ]
        response = self.client.post(self.describe_edit_url, self.get_dict())

        self.addon = self.get_addon()
        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id]

        # Make sure the categories list we display to the user in the response
        # has been updated.
        assert response.context['addon'].all_categories == (self.addon.all_categories)

    def test_edit_categories_required(self):
        del self.cat_initial['categories']
        response = self.client.post(self.describe_edit_url, self.cat_initial)
        assert response.context['cat_form'].errors['categories'] == (
            ['This field is required.']
        )

    def test_edit_categories_max(self):
        assert amo.MAX_CATEGORIES == 3
        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['bookmarks'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['social-communication'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['games-entertainment'].id,
        ]
        response = self.client.post(self.describe_edit_url, self.cat_initial)
        assert response.context['cat_form'].errors['categories'] == (
            ['You can have only 3 categories.']
        )

    def test_edit_categories_other_failure(self):
        self.cat_initial['categories'] = [
            CATEGORIES[amo.ADDON_EXTENSION]['other'].id,
            CATEGORIES[amo.ADDON_EXTENSION]['feeds-news-blogging'].id,
        ]
        response = self.client.post(self.describe_edit_url, self.cat_initial)
        assert response.context['cat_form'].errors['categories'] == (
            [
                'The miscellaneous category cannot be combined with additional '
                'categories.'
            ]
        )

    def test_edit_categories_nonexistent(self):
        self.cat_initial['categories'] = [100]
        response = self.client.post(self.describe_edit_url, self.cat_initial)
        assert response.context['cat_form'].errors['categories'] == (
            ['Select a valid choice. 100 is not one of the available choices.']
        )

    def test_nav_links_admin(self):
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))
        response = self.client.get(self.url)
        doc = pq(response.content)('#edit-addon-nav')
        links = doc('ul:last').find('li a')
        assert links.eq(1).attr('href') == reverse(
            'reviewers.review', args=[self.addon.pk]
        )
        assert links.eq(2).attr('href') == reverse(
            'reviewers.review', args=['unlisted', self.addon.pk]
        )
        assert links.eq(3).attr('href') == reverse(
            'admin:addons_addon_change', args=[self.addon.id]
        )

    def test_not_experimental_flag(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#experimental-edit').text() == (
            'This add-on is ready for general use.'
        )

    def test_experimental_flag(self):
        self.get_addon().update(is_experimental=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#experimental-edit').text() == ('This add-on is experimental.')

    def test_not_requires_payment_flag(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#requires-payment-edit').text() == (
            "This add-on doesn't require any additional payments, "
            'paid services or software, or additional hardware.'
        )

    def test_requires_payment_flag(self):
        self.get_addon().update(requires_payment=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#requires-payment-edit').text() == (
            'This add-on requires payment, non-free services or '
            'software, or additional hardware.'
        )

    def test_edit_support(self):
        data = {'support_email': 'sjobs@apple.com', 'support_url': 'http://apple.com/'}

        self.client.post(self.describe_edit_url, self.get_dict(**data))
        addon = self.get_addon()

        for k in data:
            assert str(getattr(addon, k)) == data[k]

    def test_edit_support_optional_url(self):
        data = {'support_email': 'sjobs@apple.com', 'support_url': ''}

        self.client.post(self.describe_edit_url, self.get_dict(**data))
        addon = self.get_addon()

        for k in data:
            assert str(getattr(addon, k)) == data[k]

    def test_edit_support_optional_email(self):
        data = {'support_email': '', 'support_url': 'http://apple.com/'}

        self.client.post(self.describe_edit_url, self.get_dict(**data))
        addon = self.get_addon()

        for k in data:
            assert str(getattr(addon, k)) == data[k]

    @override_switch('content-optimization', active=True)
    def test_description_not_optional(self):
        addon = self.get_addon()
        addon.description = 'something!'
        addon.save()
        data = self.get_dict(description='')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'main_form', 'description', 'This field is required.'
        )
        assert self.get_addon().description != ''

        data['description'] = '123456789'
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'description',
            'Ensure this value has at least 10 characters (it has 9).',
        )
        assert self.get_addon().description != ''

        # Finally, test success - a description of 10+ characters.
        data['description'] = '1234567890'
        self.client.post(self.describe_edit_url, data)
        assert self.get_addon().description == '1234567890'

    def test_description_min_length_not_in_html_attrs(self):
        """Override from BaseTestEditDescribe - need to check present too."""
        # Check the min-length attribute isn't in tag when waffle is off.
        with override_switch('content-optimization', active=False):
            response = self.client.get(self.describe_edit_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#trans-description textarea').attr('minlength')
        # But min-length attribute is in tag when waffle is on.
        with override_switch('content-optimization', active=True):
            response = self.client.get(self.describe_edit_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#trans-description textarea').attr('minlength') == '10'

    def test_edit_description_does_not_affect_privacy_policy(self):
        # Regression test for #10229
        addon = self.get_addon()
        addon.privacy_policy = 'My polïcy!'
        addon.save()
        data = self.get_dict(description='Sométhing descriptive.')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        addon = Addon.objects.get(pk=addon.pk)
        assert addon.privacy_policy_id
        assert addon.privacy_policy == 'My polïcy!'
        assert addon.description_id
        assert addon.description == 'Sométhing descriptive.'

    def test_no_edit_if_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        # When an add-on is mozilla-disabled and has no listed versions, being
        # the author is not enough to see it in devhub, you'll get a 404. If
        # it has listed versions, they are allowed to see it.
        expected_status_code = 200 if self.listed else 404
        response = self.client.get(self.url)
        assert response.status_code == expected_status_code

        doc = pq(response.content)
        # Images section would be broken and should not be displayed.
        assert len(doc('h3')) == 3
        assert 'Images' not in doc('h3').text()

        # In any case they won't be able to edit it.
        response = self.client.post(self.describe_edit_url, self.get_dict())
        assert response.status_code == 403


class TestEditDescribeUnlisted(BaseTestEditDescribe, L10nTestsMixin):
    listed = False
    __test__ = True


class TestEditMedia(BaseTestEdit):
    __test__ = True

    def setUp(self):
        super().setUp()
        self.media_edit_url = self.get_url('media', True)
        self.icon_upload = reverse('devhub.addons.upload_icon', args=[self.addon.slug])
        self.preview_upload = reverse(
            'devhub.addons.upload_preview', args=[self.addon.slug]
        )

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
            ['image/jpeg', 'image/png']
        )
        assert field.attr('data-upload-url') == self.icon_upload

    def test_edit_media_defaulticon(self):
        data = {'icon_type': ''}
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()

        assert (
            addon.get_icon_url(64)
            == 'http://testserver/static/img/addon-icons/default-64.png'
        )

        for k in data:
            assert str(getattr(addon, k)) == data[k]

    def test_edit_media_shows_proper_labels(self):
        """Regression test for

        https://github.com/mozilla/addons-server/issues/8900"""
        doc = pq(self.client.get(self.media_edit_url).content)

        labels = doc('#icons_default li a~label')

        assert labels.length == 1

        # First one is the default icon
        assert labels[0].get('for') == 'id_icon_type_0_0'
        assert labels[0].find('input').get('name') == 'icon_type'
        assert labels[0].find('input').get('value') == ''

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

    def test_edit_media_uploadedicon(self):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(force_str(response.content))
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = {
            'icon_type': 'image/png',
            'icon_upload_hash': response_json['upload_hash'],
        }
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        url = addon.get_icon_url(64)
        assert ('addon_icons/3/%s' % addon.id) in url, 'Unexpected path: %r' % url

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(
            settings.MEDIA_ROOT, 'addon_icons', '%s' % (addon.id // 1000)
        )
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert storage.exists(dest)

        assert image_size(dest) == (32, 12)

        assert addon.icon_type == 'image/png'
        assert addon.icon_hash == 'bb362450'

    def test_edit_media_icon_log(self):
        self.test_edit_media_uploadedicon()
        log = ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id)
        assert log.count() == 1
        assert log[0].action == amo.LOG.CHANGE_MEDIA.id

    def test_edit_media_uploadedicon_noresize(self):
        img = 'static/img/notifications/error.png'
        src_image = open(img, 'rb')

        data = {'upload_image': src_image}

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(force_str(response.content))
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = {
            'icon_type': 'image/png',
            'icon_upload_hash': response_json['upload_hash'],
        }
        data_formset = self.formset_media(**data)

        response = self.client.post(self.media_edit_url, data_formset)
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()

        # Unfortunate hardcoding of URL
        addon_url = addon.get_icon_url(64).split('?')[0]
        assert addon_url.endswith('addon_icons/3/%s-64.png' % addon.id), (
            'Unexpected path: %r' % addon_url
        )

        assert data['icon_type'] == 'image/png'

        # Check that it was actually uploaded
        dirname = os.path.join(
            settings.MEDIA_ROOT, 'addon_icons', '%s' % (addon.id // 1000)
        )
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert storage.exists(dest)

        assert image_size(dest) == (48, 48)

        assert addon.icon_type == 'image/png'
        assert addon.icon_hash == 'f02063c9'

    def check_image_type(self, url, msg):
        img = 'static/js/zamboni/devhub.js'
        src_image = open(img, 'rb')

        res = self.client.post(url, {'upload_image': src_image})
        response_json = json.loads(force_str(res.content))
        assert response_json['errors'][0] == msg

    def test_edit_media_icon_wrong_type(self):
        self.check_image_type(self.icon_upload, 'Icons must be either PNG or JPG.')

    def test_edit_media_screenshot_wrong_type(self):
        self.check_image_type(self.preview_upload, 'Images must be either PNG or JPG.')

    @override_settings(MAX_IMAGE_UPLOAD_SIZE=10 * 1024)
    def test_image_too_big(self):
        response = self.client.post(
            self.preview_upload,
            {'upload_image': open(get_image_path('mozilla-small.png'), 'rb')},
        )
        data = json.loads(force_str(response.content))
        assert data == {
            'errors': ['Please use images smaller than 0MB.'],
            'upload_hash': '',
        }

    @override_settings(MAX_ICON_UPLOAD_SIZE=10 * 1024)
    def test_icon_too_big(self):
        response = self.client.post(
            self.icon_upload,
            {'upload_image': open(get_image_path('mozilla-small.png'), 'rb')},
        )
        data = json.loads(force_str(response.content))
        assert data == {
            'errors': ['Please use images smaller than 0MB.'],
            'upload_hash': '',
        }

    def setup_image_status(self):
        addon = self.get_addon()
        self.icon_dest = os.path.join(addon.get_icon_dir(), '%s-32.png' % addon.id)
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
        result = json.loads(force_str(self.client.get(url).content))
        assert result['icons']

    def test_image_status_works(self):
        self.setup_image_status()
        result = json.loads(force_str(self.client.get(self.url).content))
        assert result['icons']

    def test_image_status_fails(self):
        self.setup_image_status()
        storage.delete(self.icon_dest)
        result = json.loads(force_str(self.client.get(self.url).content))
        assert not result['icons']

    def test_preview_status_works(self):
        self.setup_image_status()
        result = json.loads(force_str(self.client.get(self.url).content))
        assert result['previews']

        # No previews means that all the images are done.
        self.addon.previews.all().delete()
        result = json.loads(force_str(self.client.get(self.url).content))
        assert result['previews']

    def test_preview_status_fails(self):
        self.setup_image_status()
        storage.delete(self.preview.thumbnail_path)
        result = json.loads(force_str(self.client.get(self.url).content))
        assert not result['previews']

    def check_image_animated(self, url, msg):
        filehandle = open(get_image_path('animated.png'), 'rb')

        res = self.client.post(url, {'upload_image': filehandle})
        response_json = json.loads(force_str(res.content))
        assert response_json['errors'][0] == msg

    def test_icon_animated(self):
        self.check_image_animated(self.icon_upload, 'Icons cannot be animated.')

    def test_screenshot_animated(self):
        self.check_image_animated(self.preview_upload, 'Images cannot be animated.')

    @override_switch('content-optimization', active=True)
    def test_icon_dimensions_and_ratio(self):
        size_msg = 'Icon must be at least 128 pixels wide and tall.'
        ratio_msg = 'Icon must be square (same width and height).'

        # mozilla-snall.png is too small and not square
        response = self.client.post(
            self.icon_upload,
            {'upload_image': open(get_image_path('mozilla-small.png'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == [
            size_msg,
            ratio_msg,
        ]

        # icon64.png is the right ratio, but only 64x64
        response = self.client.post(
            self.icon_upload, {'upload_image': open(get_image_path('icon64.png'), 'rb')}
        )
        assert json.loads(force_str(response.content))['errors'] == [size_msg]

        # mozilla.png is big enough but still not square
        response = self.client.post(
            self.icon_upload,
            {'upload_image': open(get_image_path('mozilla.png'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == [ratio_msg]

        # and mozilla-sq is the right ratio and big enough
        response = self.client.post(
            self.icon_upload,
            {'upload_image': open(get_image_path('mozilla-sq.png'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == []
        assert json.loads(force_str(response.content))['upload_hash']

    def preview_add(self, amount=1, image_name='preview_4x3.jpg'):
        src_image = open(get_image_path(image_name), 'rb')

        data = {'upload_image': src_image}
        data_formset = self.formset_media(**data)
        url = self.preview_upload
        response = self.client.post(url, data_formset)

        details = json.loads(force_str(response.content))
        upload_hash = details['upload_hash']

        # Create and post with the formset.
        fields = []
        for i in range(amount):
            fields.append(
                self.formset_new_form(caption='hi', upload_hash=upload_hash, position=i)
            )
        data_formset = self.formset_media(*fields)
        self.client.post(self.media_edit_url, data_formset)

    @override_switch('content-optimization', active=False)
    def test_edit_media_preview_add(self):
        # mozilla.png is too small and the wrong ratio but waffle is off so OK.
        self.preview_add(image_name='mozilla.png')

        assert str(self.get_addon().previews.all()[0].caption) == 'hi'

    @override_switch('content-optimization', active=True)
    def test_edit_media_preview_add_content_optimization(self):
        self.preview_add()

        assert str(self.get_addon().previews.all()[0].caption) == 'hi'

    @override_switch('content-optimization', active=True)
    def test_preview_dimensions_and_ratio(self):
        size_msg = 'Image must be at least 1000 pixels wide and 750 pixels tall.'
        ratio_msg = 'Image dimensions must be in the ratio 4:3.'

        # mozilla.png is too small and the wrong ratio now
        response = self.client.post(
            self.preview_upload,
            {'upload_image': open(get_image_path('mozilla.png'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == [
            size_msg,
            ratio_msg,
        ]

        # preview_landscape.jpg is the right ratio-ish, but too small
        response = self.client.post(
            self.preview_upload,
            {'upload_image': open(get_image_path('preview_landscape.jpg'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == [size_msg]

        # teamaddons.jpg is big enough but still wrong ratio.
        response = self.client.post(
            self.preview_upload,
            {'upload_image': open(get_image_path('teamaddons.jpg'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == [ratio_msg]

        # and preview_4x3.jpg is the right ratio and big enough
        response = self.client.post(
            self.preview_upload,
            {'upload_image': open(get_image_path('preview_4x3.jpg'), 'rb')},
        )
        assert json.loads(force_str(response.content))['errors'] == []
        assert json.loads(force_str(response.content))['upload_hash']

    def test_edit_media_preview_edit(self):
        self.preview_add()
        preview = self.get_addon().previews.all()[0]
        edited = {
            'caption': 'bye',
            'upload_hash': '',
            'id': preview.id,
            'position': preview.position,
            'file_upload': None,
        }

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
        edited = {
            'DELETE': 'checked',
            'upload_hash': '',
            'id': preview.id,
            'position': 0,
            'file_upload': None,
        }

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


class TagTestsMixin:
    def get_dict(self, **kw):
        result = {'default_locale': 'en-US', 'tags': self.tags}
        result.update(**kw)
        return result

    def test_edit_add_tag(self):
        count = ActivityLog.objects.filter(action=amo.LOG.ADD_TAG.id).count()
        self.tags.insert(0, 'tag4')
        Tag.objects.get_or_create(tag_text='tag4')
        data = self.get_dict()
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertNoFormErrors(response)

        assert set(
            AddonTag.objects.filter(addon=self.addon).values_list(
                'tag__tag_text', flat=True
            )
        ) == {'tag1', 'tag2', 'tag3', 'tag4'}
        result = pq(response.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))
        html = (
            '<a href="http://testserver/en-US/firefox/tag/tag4/">tag4</a> added to '
            + (
                '<a href="http://testserver/en-US/firefox/addon/a3615/">'
                'Delicious Bookmarks</a>.'
                if self.listed
                else 'Delicious Bookmarks.'
            )
        )
        assert (
            ActivityLog.objects.for_addons(self.addon)
            .get(action=amo.LOG.ADD_TAG.id)
            .to_string()
            == html
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.ADD_TAG.id).count() == count + 1
        )

    def test_cannot_create_new_tag(self):
        start = Tag.objects.all().count()
        data = self.get_dict(tags='create_tag')
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200

        error = 'Select a valid choice. create_tag is not one of the available choices.'
        self.assertFormError(response, 'main_form', 'tags', error)

        # Check that the tag did not get created.
        assert start == Tag.objects.all().count()

    def test_edit_remove_tag(self):
        self.tags.remove('tag2')

        count = ActivityLog.objects.filter(action=amo.LOG.ADD_TAG.id).count()
        data = self.get_dict()
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertNoFormErrors(response)

        assert set(
            AddonTag.objects.filter(addon=self.addon).values_list(
                'tag__tag_text', flat=True
            )
        ) == {'tag1', 'tag3'}

        result = pq(response.content)('#addon_tags_edit').eq(0).text()

        assert result == ', '.join(sorted(self.tags))

        assert (
            ActivityLog.objects.filter(action=amo.LOG.REMOVE_TAG.id).count()
            == count + 1
        )

    def test_edit_max_tags(self):
        tags = self.tags

        for i in range(amo.MAX_TAGS + 1):
            Tag.objects.get_or_create(tag_text='test%d' % i)
            tags.append('test%d' % i)

        data = self.get_dict()
        response = self.client.post(self.details_edit_url, data)
        self.assertFormError(
            response,
            'main_form',
            'tags',
            'You have %d too many tags.' % (len(tags) - amo.MAX_TAGS),
        )


class ContributionsTestsMixin:
    def test_contributions_url_not_url(self):
        data = self.get_dict(default_locale='en-US', contributions='foooo')
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'main_form', 'contributions', 'Enter a valid URL.'
        )

    def test_contributions_url_not_valid_domain(self):
        data = self.get_dict(default_locale='en-US', contributions='https://foo.baa/')
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'contributions',
            'URL domain must be one of [%s].'
            % ', '.join(amo.VALID_CONTRIBUTION_DOMAINS),
        )

    def test_contributions_url_not_valid_github_sponsors_path(self):
        assert 'github.com' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(
            default_locale='en-US', contributions='https://github.com/random/'
        )
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'contributions',
            'URL path for GitHub Sponsors must contain /sponsors/.',
        )

    def test_contributions_url_not_valid_domain_sub(self):
        assert 'paypal.me' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(
            default_locale='en-US', contributions='https://sub.paypal.me/random/?path'
        )
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'contributions',
            'URL domain must be one of [%s].'
            % ', '.join(amo.VALID_CONTRIBUTION_DOMAINS),
        )

    def test_contributions_url_not_https_domain(self):
        assert 'paypal.me' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(default_locale='en-US', contributions='http://paypal.me/')
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'main_form',
            'contributions',
            'URLs must start with https://.',
        )

    def test_contributions_url_valid_domain(self):
        assert 'paypal.me' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(default_locale='en-US', contributions='https://paypal.me/')
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertNoFormErrors(response)
        assert self.addon.reload().contributions == 'https://paypal.me/'

    def test_contributions_url_valid_github_sponsors_path(self):
        assert 'github.com' in amo.VALID_CONTRIBUTION_DOMAINS
        data = self.get_dict(
            default_locale='en-US', contributions='https://github.com/sponsors/random/'
        )
        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        self.assertNoFormErrors(response)
        assert self.addon.reload().contributions == (
            'https://github.com/sponsors/random/'
        )


class BaseTestEditAdditionalDetails(BaseTestEdit):
    __test__ = False

    def setUp(self):
        super().setUp()
        self.details_url = self.get_url('additional_details')
        self.details_edit_url = self.get_url('additional_details', edit=True)

    def test_edit(self):
        data = {'default_locale': 'en-US', 'homepage': 'http://twitter.com/fligtarsmom'}
        response = self.client.get(self.details_edit_url)
        assert response.status_code == 200

        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert str(getattr(addon, k)) == data[k]

    def test_edit_homepage_optional(self):
        data = {'default_locale': 'en-US', 'homepage': ''}

        response = self.client.post(self.details_edit_url, data)
        assert response.status_code == 200
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()

        for k in data:
            assert str(getattr(addon, k)) == data[k]


class TestEditAdditionalDetailsListed(
    BaseTestEditAdditionalDetails, TagTestsMixin, ContributionsTestsMixin
):
    __test__ = True

    def test_edit_default_locale_required_trans(self):
        # name, summary, and description are required in the new locale.
        error = (
            'Before changing your default locale you must have a name, '
            'summary, and description in that locale. '
            'You are missing '
        )

        data = {'homepage': str(self.addon.homepage), 'default_locale': 'fr'}
        response = self.client.post(self.details_edit_url, data)
        # We can't use assertFormError here, because the missing fields are
        # stored in a dict, which isn't ordered.
        form_error = response.context['main_form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'name'" in form_error
        assert "'summary'" in form_error

        # Now we have a name.
        self.addon.name = {'fr': 'fr name'}
        self.addon.save()
        response = self.client.post(self.details_edit_url, data)
        form_error = response.context['main_form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error
        assert "'summary'" in form_error

        # Now we have a summary.
        self.addon.summary = {'fr': 'fr summary'}
        self.addon.save()
        response = self.client.post(self.details_edit_url, data)
        form_error = response.context['main_form'].non_field_errors()[0]
        assert form_error.startswith(error)
        assert "'description'" in form_error

        # And finally a description.
        self.addon.description = {'fr': 'fr description'}
        self.addon.save()
        response = self.client.post(self.details_edit_url, data)
        assert response.context['main_form'].errors == {}

    def test_edit_default_locale_frontend_error(self):
        data = {'homepage': 'https://staticfil.es/', 'default_locale': 'fr'}
        response = self.client.post(self.details_edit_url, data)
        self.assertContains(response, 'Before changing your default locale you must')

    def test_edit_locale(self):
        addon = self.get_addon()
        addon.update(default_locale='en-US')
        response = self.client.get(self.details_url)
        assert pq(response.content)('.addon_edit_locale').eq(0).text() == (
            'English (US)'
        )


class TestEditAdditionalDetailsUnlisted(TagTestsMixin, BaseTestEditAdditionalDetails):
    listed = False
    __test__ = True


class TestEditTechnical(BaseTestEdit):
    __test__ = True
    fixtures = BaseTestEdit.fixtures + [
        'base/addon_40',
        'base/addon_1833_yoono',
        'base/addon_4664_twitterbar.json',
        'base/addon_5299_gcal',
        'base/addon_6113',
    ]

    def setUp(self):
        super().setUp()
        self.technical_url = self.get_url('technical')
        self.technical_edit_url = self.get_url('technical', edit=True)

    def test_log(self):
        data = {'developer_comments': 'This is a test'}
        assert ActivityLog.objects.exclude(action=amo.LOG.LOG_IN.id).count() == 0
        response = self.client.post(self.technical_edit_url, data)
        assert response.context['main_form'].errors == {}
        assert (
            ActivityLog.objects.filter(action=amo.LOG.EDIT_PROPERTIES.id).count() == 1
        )

    def test_technical_on(self):
        # Turn everything on
        data = {
            'developer_comments': 'Test comment!',
            'whiteboard-public': 'Whiteboard info.',
        }

        response = self.client.post(self.technical_edit_url, data)
        assert response.context['main_form'].errors == {}

        addon = self.get_addon()
        for k in data:
            if k == 'developer_comments':
                assert str(getattr(addon, k)) == str(data[k])
            elif k == 'whiteboard-public':
                assert str(addon.whiteboard.public) == str(data[k])
            else:
                assert getattr(addon, k) == (data[k] == 'on')

    def test_whiteboard_too_long(self):
        data = {
            'whiteboard-public': 'ê' * 100001,
        }
        response = self.client.post(self.technical_edit_url, data)
        assert response.context['whiteboard_form'].errors == {
            'public': [
                'Ensure this value has at most 100000 characters (it has 100001).'
            ]
        }


class TestEditTechnicalUnlisted(BaseTestEdit):
    __test__ = True
    listed = False

    def setUp(self):
        super().setUp()
        self.technical_url = self.get_url('technical')
        self.technical_edit_url = self.get_url('technical', edit=True)

    def test_whiteboard(self):
        # It's okay to post empty whiteboard instructions.
        response = self.client.post(self.technical_edit_url, {'whiteboard-public': ''})
        assert response.context['main_form'].errors == {}

        # Let's update it.
        response = self.client.post(
            self.technical_edit_url, {'whiteboard-public': 'important stuff'}
        )
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()
        assert addon.whiteboard.public == 'important stuff'

        # And clear it again.
        response = self.client.post(self.technical_edit_url, {'whiteboard-public': ''})
        assert response.context['main_form'].errors == {}
        addon = self.get_addon()
        assert addon.whiteboard.public == ''


class StaticMixin:
    def setUp(self):
        super().setUp()
        addon = self.get_addon()
        addon.update(type=amo.ADDON_STATICTHEME)
        if self.listed:
            AddonCategory.objects.filter(addon=addon).delete()
            VersionPreview.objects.create(version=addon.current_version)


class TestEditDescribeStaticThemeListed(
    StaticMixin, BaseTestEditDescribe, L10nTestsMixin
):
    __test__ = True

    def get_dict(self, **kw):
        result = {
            'name': 'new name',
            'slug': 'test_slug',
            'summary': 'new summary',
            'description': 'new description',
            'category': 'abstract',
        }
        result.update(**kw)
        return result

    def test_edit_categories_set(self):
        assert [cat.id for cat in self.get_addon().all_categories] == []
        response = self.client.post(
            self.describe_edit_url, self.get_dict(categories=[308])
        )
        assert response.context['addon'].all_categories == (
            self.get_addon().all_categories
        )

        addon_cats = [c.id for c in self.get_addon().all_categories]
        assert sorted(addon_cats) == [308]

    def test_edit_categories_change(self):
        AddonCategory(addon=self.addon, category_id=300).save()
        assert sorted(cat.id for cat in self.get_addon().all_categories) == [300]

        self.client.post(self.describe_edit_url, self.get_dict(categories=[308]))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        # Only ever one category for Static Themes (per application)
        assert category_ids_new == [308]

    def test_edit_categories_required(self):
        data = self.get_dict(categories='')
        response = self.client.post(self.describe_edit_url, data)
        assert response.status_code == 200
        self.assertFormError(
            response, 'cat_form', 'categories', 'This field is required.'
        )

    def test_theme_preview_shown(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert 'Preview' in doc('h3').text()
        assert doc('div.edit-addon-section img')[0].attrib['src'] == (
            self.addon.current_version.previews.first().image_url
        )
        assert len(doc('div.edit-addon-section img')) == 1  # Just one preview.

    def test_theme_preview_not_shown_mozilla_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert 'Preview' not in doc('h3').text()
        assert len(doc('div.edit-addon-section img')) == 0


class TestEditDescribeStaticThemeUnlisted(StaticMixin, TestEditDescribeUnlisted):
    def test_theme_preview_not_shown(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert 'Preview' not in doc('h3').text()


class TestEditAdditionalDetailsStaticThemeListed(
    StaticMixin, TestEditAdditionalDetailsListed
):
    pass


class TestEditAdditionalDetailsStaticThemeUnlisted(
    StaticMixin, TestEditAdditionalDetailsUnlisted
):
    pass


class TestEditTechnicalStaticThemeListed(StaticMixin, TestEditTechnicalUnlisted):
    # Using the Unlisted test case because it's got the right tests for us.
    listed = True


class TestEditTechnicalStaticThemeUnlisted(StaticMixin, TestEditTechnicalUnlisted):
    pass


class TestStatsLinkInSidePanel(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.addon = addon_factory(users=[self.user])
        self.url = reverse('devhub.addons.edit', args=[self.addon.slug])
        self.client.force_login(self.user)

    def test_link_to_stats(self):
        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_link_to_stats_for_langpacks(self):
        self.addon.update(type=amo.ADDON_LPAPP)
        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_link_to_stats_for_dicts(self):
        self.addon.update(type=amo.ADDON_DICT)
        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )
