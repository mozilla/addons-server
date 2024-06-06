import json
import os
import zipfile
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core import mail
from django.test import RequestFactory
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.translation import trim_whitespace

import freezegun
import pytest
import responses
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.accounts.utils import fxa_login_url
from olympia.activity.models import GENERIC_USER_NAME, ActivityLog
from olympia.addons.models import Addon, AddonCategory, AddonReviewerFlags, AddonUser
from olympia.amo.templatetags.jinja_helpers import (
    format_date,
    url as url_reverse,
    urlparams,
)
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.api.models import SYMMETRIC_JWT_TYPE, APIKey, APIKeyConfirmation
from olympia.applications.models import AppVersion
from olympia.constants.promoted import RECOMMENDED
from olympia.devhub.decorators import dev_required
from olympia.devhub.models import BlogPost
from olympia.devhub.tasks import validate
from olympia.devhub.views import get_next_version_number
from olympia.files.models import FileUpload
from olympia.files.tests.test_models import UploadMixin
from olympia.ratings.models import Rating
from olympia.translations.models import Translation, delete_translation
from olympia.users.models import (
    IPNetworkUserRestriction,
    SuppressedEmail,
    SuppressedEmailVerification,
    UserProfile,
)
from olympia.users.tests.test_views import UserViewBase
from olympia.versions.models import Version, VersionPreview
from olympia.zadmin.models import set_config


class HubTest(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.index')
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        assert self.client.get(self.url).status_code == 200
        self.user_profile = UserProfile.objects.get(id=999)
        not_their_addon = addon_factory(users=[user_factory()])
        AddonUser.unfiltered.create(
            addon=not_their_addon, user=self.user_profile, role=amo.AUTHOR_ROLE_DELETED
        )

    def clone_addon(self, num, addon_id=3615):
        addons = []
        source = Addon.objects.get(id=addon_id)
        for i in range(num):
            data = {
                'type': source.type,
                'status': source.status,
                'name': f'cloned-addon-{addon_id}-{i}',
                'users': [self.user_profile],
            }
            addons.append(addon_factory(**data))
        return addons


class TestDashboard(HubTest):
    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.addons')
        self.themes_url = reverse('devhub.themes')
        assert self.client.get(self.url).status_code == 200
        self.addon = Addon.objects.get(pk=3615)
        self.addon.addonuser_set.create(user=self.user_profile)

    def test_addons_layout(self):
        doc = pq(self.client.get(self.url).content)
        assert doc('title').text() == (
            'Manage My Submissions :: Developer Hub :: Add-ons for Firefox'
        )
        assert doc('.Footer-links').length == 4
        assert doc('.Footer-copyright').length == 1

    def get_action_links(self, addon_id):
        response = self.client.get(self.url)
        doc = pq(response.content)
        selector = '.item[data-addonid="%s"] .item-actions li > a' % addon_id
        links = [a.text.strip() for a in doc(selector)]
        return links

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.item item').length == 0

    def test_addon_pagination(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 10 add-ons.  We going to make the existing one from the setUp
        # and a static theme which shouldn't show up as an addon in this list.
        addons = self.clone_addon(10)
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 10
        assert len(doc('.item .info.extension')) == 10
        assert doc('ol.pagination').length == 0
        for addon in addons:
            assert addon.get_icon_url(64) in doc('.item .info h3 a').html()

        # Create 5 add-ons -have to change self.addon back to clone extensions.
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.clone_addon(5)
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url, {'page': 2})
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 5
        assert doc('ol.pagination').length == 1

    def test_themes(self):
        """Check themes show on dashboard."""
        # Create 2 themes.
        staticthemes = []
        for _x in range(2):
            addon = addon_factory(type=amo.ADDON_STATICTHEME, users=[self.user_profile])
            VersionPreview.objects.create(version=addon.current_version)
            staticthemes.append(addon)
        response = self.client.get(self.themes_url)
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 2
        assert len(doc('.item .info.statictheme')) == 2
        for addon in staticthemes:
            assert addon.current_previews[0].thumbnail_url in [
                img.attrib['src'] for img in doc('.info.statictheme h3 img')
            ]

    def test_show_hide_statistics_and_new_version_for_disabled(self):
        # Not disabled: show statistics and new version links.
        self.addon.update(disabled_by_user=False)
        links = self.get_action_links(self.addon.pk)
        assert 'Statistics' in links, 'Unexpected: %r' % links
        assert 'New Version' in links, 'Unexpected: %r' % links

        # Disabled (user): hide new version link.
        self.addon.update(disabled_by_user=True)
        links = self.get_action_links(self.addon.pk)
        assert 'New Version' not in links, 'Unexpected: %r' % links

        # Disabled (admin): hide statistics and new version links.
        self.addon.update(disabled_by_user=False, status=amo.STATUS_DISABLED)
        links = self.get_action_links(self.addon.pk)
        assert 'Statistics' not in links, 'Unexpected: %r' % links
        assert 'New Version' not in links, 'Unexpected: %r' % links

    def test_public_addon(self):
        assert self.addon.status == amo.STATUS_APPROVED
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid="%s"]' % self.addon.id)
        assert item.find('h3 a').attr('href') == self.addon.get_dev_url()
        assert item.find('p.downloads'), 'Expected weekly downloads'
        assert item.find('p.users'), 'Expected ADU'
        assert item.find('.item-details'), 'Expected item details'
        assert not item.find(
            'p.incomplete'
        ), 'Unexpected message about incomplete add-on'

        appver = self.addon.current_version.apps.all()[0]
        appver.delete()

    def test_dev_news(self):
        for i in range(7):
            bp = BlogPost(
                title='hi %s' % i,
                date_posted=datetime.now() - timedelta(days=i),
            )
            bp.save()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert doc('.blog-posts').length == 1
        assert doc('.blog-posts li').length == 5
        assert doc('.blog-posts li a').eq(0).text() == 'hi 0'
        assert doc('.blog-posts li a').eq(4).text() == 'hi 4'

    def test_dev_news_xss(self):
        BlogPost.objects.create(
            title='<script>alert(42)</script>', date_posted=datetime.now()
        )
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert doc('.blog-posts').length == 1
        assert doc('.blog-posts li').length == 1
        assert doc('.blog-posts li a').eq(0).text() == '<script>alert(42)</script>'
        assert b'<script>alert(42)</script>' not in response.content

    def test_sort_created_filter(self):
        response = self.client.get(self.url + '?sort=created')
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        elm = doc('.item-details .date-created')
        assert elm.length == 1
        assert elm.remove('strong').text() == (format_date(self.addon.created))

    def test_sort_updated_filter(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        elm = doc('.item-details .date-updated')
        assert elm.length == 1
        assert elm.remove('strong').text() == (
            trim_whitespace(format_date(self.addon.last_updated))
        )

    def test_purely_unlisted_addon_are_not_shown_as_incomplete(self):
        self.make_addon_unlisted(self.addon)
        assert self.addon.has_complete_metadata()

        response = self.client.get(self.url)
        doc = pq(response.content)
        # It should not be considered incomplete despite having STATUS_NULL,
        # since it's purely unlisted.
        assert not doc('.incomplete')

        # Rest of the details should be shown, but not the AMO-specific stuff.
        assert not doc('.item-info')
        assert doc('.item-details')

    def test_mixed_versions_addon_with_incomplete_metadata(self):
        self.make_addon_unlisted(self.addon)
        version = version_factory(addon=self.addon, channel=amo.CHANNEL_LISTED)
        version.update(license=None)
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.reload()
        assert not self.addon.has_complete_metadata()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.incomplete').text() == (
            'This add-on is missing some required information before it can be'
            ' submitted for publication.'
        )
        assert doc('form.resume').attr('action') == (
            url_reverse('devhub.request-review', self.addon.slug)
        )
        assert doc('button.link').text() == 'Resume'

    def test_no_versions_addon(self):
        self.addon.current_version.delete()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.incomplete').text() == ("This add-on doesn't have any versions.")


class TestDevRequired(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.edit_page_url = self.addon.get_dev_url('edit')
        self.get_url = self.addon.get_dev_url('versions')
        self.delete_url = self.addon.get_dev_url('delete')
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))
        self.au = self.addon.addonuser_set.get(user__email='del@icio.us')
        assert self.au.role == amo.AUTHOR_ROLE_OWNER

    def test_anon(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.get(self.get_url), self.get_url)
        self.assertLoginRedirects(
            self.client.get(self.edit_page_url), self.edit_page_url
        )

    def test_dev_get(self):
        response = self.client.get(self.get_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'no-edit' not in doc('body')[0].attrib['class']
        response = self.client.get(self.edit_page_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'no-edit' not in doc('body')[0].attrib['class']

    def test_dev_post(self):
        self.assert3xx(self.client.post(self.delete_url), self.get_url)

    def test_disabled_post_owner(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.get_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'no-edit' in doc('body')[0].attrib['class']
        assert self.client.post(self.delete_url).status_code == 403

    def test_disabled_post_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))
        response = self.client.get(self.get_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'no-edit' not in doc('body')[0].attrib['class']
        self.assert3xx(self.client.post(self.delete_url), self.get_url)


class TestVersionStats(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))

    def test_counts(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = UserProfile.objects.get(email='admin@mozilla.com')
        for _ in range(10):
            Rating.objects.create(addon=addon, user=user, version=addon.current_version)

        url = reverse('devhub.versions.stats', args=[addon.slug])
        data = json.loads(force_str(self.client.get(url).content))
        exp = {
            str(version.id): {
                'reviews': 10,
                'files': 1,
                'version': version.version,
                'id': version.id,
            }
        }
        self.assertDictEqual(data, exp)


class TestDelete(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.get_addon = lambda: Addon.objects.filter(id=3615)
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.get_url = lambda: self.get_addon()[0].get_dev_url('delete')

    def test_post_not(self):
        response = self.client.post(self.get_url(), follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.'
        )
        assert self.get_addon().exists()
        self.assert3xx(response, self.get_addon()[0].get_dev_url('versions'))

    def test_post(self):
        self.get_addon().get().update(slug='addon-slug')
        response = self.client.post(self.get_url(), {'slug': 'addon-slug'}, follow=True)
        assert pq(response.content)('.notification-box').text() == ('Add-on deleted.')
        assert not self.get_addon().exists()
        self.assert3xx(response, reverse('devhub.addons'))

    def test_post_wrong_slug(self):
        self.get_addon().get().update(slug='addon-slug')
        response = self.client.post(self.get_url(), {'slug': 'theme-slug'}, follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.'
        )
        assert self.get_addon().exists()
        self.assert3xx(response, self.get_addon()[0].get_dev_url('versions'))

    def test_post_statictheme(self):
        theme = addon_factory(
            name='xpi name',
            type=amo.ADDON_STATICTHEME,
            slug='stheme-slug',
            users=[self.user],
        )
        response = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'stheme-slug'}, follow=True
        )
        assert pq(response.content)('.notification-box').text() == ('Theme deleted.')
        assert not Addon.objects.filter(id=theme.id).exists()
        self.assert3xx(response, reverse('devhub.themes'))

    def test_post_statictheme_wrong_slug(self):
        theme = addon_factory(
            name='xpi name',
            type=amo.ADDON_STATICTHEME,
            slug='stheme-slug',
            users=[self.user],
        )
        response = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'foo-slug'}, follow=True
        )
        assert pq(response.content)('.notification-box').text() == (
            'URL name was incorrect. Theme was not deleted.'
        )
        assert Addon.objects.filter(id=theme.id).exists()
        self.assert3xx(response, theme.get_dev_url('versions'))


class TestHome(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super().setUp()
        self.user_profile = UserProfile.objects.get(email='del@icio.us')
        self.client.force_login(self.user_profile)
        self.url = reverse('devhub.index')
        self.addon = Addon.objects.get(pk=3615)

    def get_pq(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        return pq(response.content)

    def test_basic_logged_out(self):
        self.client.logout()
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'devhub/index.html')
        assert b'Customize Firefox' in response.content

    def test_default_lang_selected(self):
        self.client.logout()
        doc = self.get_pq()
        selected_value = doc('#language option:selected').attr('value')
        assert selected_value == 'en-us'

    @override_switch('suppressed-email', active=True)
    def test_suppressed_email_logged_out(self):
        self.client.logout()
        SuppressedEmail.objects.create(email=self.user_profile.email)

        doc = self.get_pq()

        assert doc('#suppressed-email').length == 0

    @override_switch('suppressed-email', active=True)
    def test_suppressed_email_displayed(self):
        SuppressedEmail.objects.create(email=self.user_profile.email)

        doc = self.get_pq()

        assert self.user_profile.email in doc('#suppressed-email').text()
        assert doc('#suppressed-email').length == 1
        assert 'Learn more' in doc('#suppressed-email a').text()
        assert reverse('devhub.email_verification') in doc('#suppressed-email a').attr(
            'href'
        )

    @override_switch('suppressed-email', active=False)
    def test_suppressed_email_hidden_by_flase(self):
        SuppressedEmail.objects.create(email=self.user_profile.email)

        doc = self.get_pq()

        assert doc('#suppressed-email').length == 0

    @override_switch('suppressed-email', active=False)
    def test_unsuppressed_email(self):
        doc = self.get_pq()

        assert doc('#suppressed-email').length == 0

    def test_basic_logged_in(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'devhub/index.html')
        assert b'My Add-ons' in response.content

    def test_my_addons_addon_versions_link(self):
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))

        doc = self.get_pq()
        addon_list = doc('.DevHub-MyAddons-list')

        href = addon_list.find('.DevHub-MyAddons-item-versions a').attr('href')
        assert href == self.addon.get_dev_url('versions')

    def test_my_addons(self):
        statuses = [
            (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, 'Awaiting Review'),
            (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW, 'Approved'),
            (amo.STATUS_DISABLED, amo.STATUS_APPROVED, 'Disabled by Mozilla'),
        ]

        latest_version = self.addon.find_latest_version(amo.CHANNEL_LISTED)
        latest_file = latest_version.file

        for addon_status, file_status, status_str in statuses:
            latest_file.update(status=file_status)
            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
            assert addon_item.length == 1
            assert addon_item.find('.DevHub-MyAddons-item-edit').attr(
                'href'
            ) == self.addon.get_dev_url('edit')
            if self.addon.type != amo.ADDON_STATICTHEME:
                assert self.addon.get_icon_url(64) in addon_item.html()
            else:
                assert self.addon.current_previews[0].thumbnail_url in (
                    addon_item.html()
                )

            assert (
                status_str == addon_item.find('.DevHub-MyAddons-VersionStatus').text()
            )

        Addon.objects.all().delete()
        assert self.get_pq()('.DevHub-MyAddons-list .DevHub-MyAddons-item').length == 0

    def test_my_addons_recommended(self):
        self.make_addon_promoted(self.addon, RECOMMENDED, approve_version=True)
        latest_version = self.addon.find_latest_version(amo.CHANNEL_LISTED)
        latest_file = latest_version.file
        statuses = [
            (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW, 'Awaiting Review'),
            (
                amo.STATUS_APPROVED,
                amo.STATUS_AWAITING_REVIEW,
                'Approved and Recommended',
            ),
            (amo.STATUS_DISABLED, amo.STATUS_APPROVED, 'Disabled by Mozilla'),
        ]

        for addon_status, file_status, status_str in statuses:
            latest_file.update(status=file_status)
            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
            assert addon_item.length == 1
            assert addon_item.find('.DevHub-MyAddons-item-edit').attr(
                'href'
            ) == self.addon.get_dev_url('edit')
            if self.addon.type != amo.ADDON_STATICTHEME:
                assert self.addon.get_icon_url(64) in addon_item.html()
            else:
                assert self.addon.current_previews[0].thumbnail_url in (
                    addon_item.html()
                )

            assert (
                status_str == addon_item.find('.DevHub-MyAddons-VersionStatus').text()
            )

        Addon.objects.all().delete()
        assert self.get_pq()('.DevHub-MyAddons-list .DevHub-MyAddons-item').length == 0

    def test_my_addons_with_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        VersionPreview.objects.create(version=self.addon.current_version)
        self.test_my_addons()

    def test_my_addons_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        # Make add-on incomplete
        AddonCategory.objects.filter(addon=self.addon).delete()
        doc = self.get_pq()
        addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
        assert addon_item.length == 1
        assert addon_item.find('.DevHub-MyAddons-item-edit').attr(
            'href'
        ) == self.addon.get_dev_url('edit')

    def test_my_addons_no_disabled_or_deleted(self):
        self.addon.update(status=amo.STATUS_APPROVED, disabled_by_user=True)
        doc = self.get_pq()

        addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
        assert addon_item.length == 1
        assert addon_item.find('.DevHub-MyAddons-VersionStatus').text() == 'Invisible'


class TestActivityFeed(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.versions.first()
        self.action_user = UserProfile.objects.get(email='reviewer@mozilla.com')
        ActivityLog.objects.all().delete()

    def test_feed_for_all(self):
        response = self.client.get(reverse('devhub.feed_all'))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('header h2').text() == 'Recent Activity for My Add-ons'

    def test_feed_for_addon(self):
        response = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('header h2').text() == ('Recent Activity for %s' % self.addon.name)

    def test_feed_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 200

    def test_feed_disabled_anon(self):
        self.client.logout()
        response = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 302

    def add_log(self, action=amo.LOG.ADD_RATING):
        core.set_user(self.action_user)
        ActivityLog.objects.create(action, self.addon, self.version)

    def add_hidden_log(self, action=amo.LOG.COMMENT_VERSION):
        self.add_log(action=action)

    def test_feed_hidden(self):
        self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        doc = pq(res.content)
        assert len(doc('#recent-activity li.item')) == 0

    def test_addons_hidden(self):
        self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        assert len(doc('.recent-activity li.item')) == 0

    def test_unlisted_addons_dashboard(self):
        """Unlisted addons are displayed in the feed on the dashboard page."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        assert len(doc('.recent-activity li.item')) == 2

    def test_unlisted_addons_feed_sidebar(self):
        """Unlisted addons are displayed in the left side in the feed page."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        # First li is "All My Add-ons".
        assert len(doc('#refine-addon li')) == 2

    def test_unlisted_addons_feed(self):
        """Unlisted addons are displayed in the feed page."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        assert len(doc('#recent-activity .item')) == 2

    def test_unlisted_addons_feed_filter(self):
        """Feed page can be filtered on unlisted addon."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        doc = pq(res.content)
        assert len(doc('#recent-activity .item')) == 2

    def test_names_for_action_users(self):
        self.add_log(action=amo.LOG.CREATE_ADDON)
        self.add_log(action=amo.LOG.APPROVE_VERSION)

        response = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        doc = pq(response.content)
        timestamp = doc('#recent-activity div.item p.timestamp')
        assert len(timestamp) == 2
        assert self.action_user.name
        assert 'by %s' % GENERIC_USER_NAME in timestamp.eq(0).html()
        assert 'by %s' % self.action_user.name in timestamp.eq(1).html()

    def test_addons_dashboard_name(self):
        self.add_log(action=amo.LOG.CREATE_ADDON)
        self.add_log(action=amo.LOG.APPROVE_VERSION)
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        timestamp = doc('.recent-activity li.item span.activity-timestamp')
        assert len(timestamp) == 2
        assert self.action_user.name
        assert 'by %s' % GENERIC_USER_NAME in timestamp.eq(0).html()
        assert 'by %s' % self.action_user.name in timestamp.eq(1).html()
        assert '<a href=' not in timestamp.eq(0).html()


class TestDeveloperAgreement(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super().setUp()
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.user.update(last_login_ip='192.168.1.1')

    def test_agreement_read(self):
        self.user.update(read_dev_agreement=self.days_ago(0))
        response = self.client.get(reverse('devhub.developer_agreement'))
        self.assert3xx(response, reverse('devhub.index'))

    def test_custom_redirect(self):
        self.user.update(read_dev_agreement=self.days_ago(0))
        response = self.client.get(
            '%s%s%s'
            % (
                reverse('devhub.developer_agreement'),
                '?to=',
                quote(reverse('devhub.api_key')),
            )
        )
        self.assert3xx(response, reverse('devhub.api_key'))

    def test_agreement_unread_captcha_inactive(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.developer_agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context
        form = response.context['agreement_form']
        assert 'recaptcha' not in form.fields
        doc = pq(response.content)
        assert doc('.g-recaptcha') == []

    @override_switch('developer-agreement-captcha', active=True)
    def test_agreement_unread_captcha_active(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.developer_agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context
        form = response.context['agreement_form']
        assert 'recaptcha' in form.fields
        doc = pq(response.content)
        assert doc('.g-recaptcha')

    def test_agreement_submit_success(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.post(
            reverse('devhub.developer_agreement'),
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        assert response.status_code == 302
        assert response['Location'] == reverse('devhub.index')
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)

    @override_switch('developer-agreement-captcha', active=True)
    def test_agreement_submit_captcha_active_error(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.post(reverse('devhub.developer_agreement'))

        # Captcha is properly rendered
        doc = pq(response.content)
        assert doc('.g-recaptcha')

        assert 'recaptcha' in response.context['agreement_form'].errors

    @override_switch('developer-agreement-captcha', active=True)
    def test_agreement_submit_captcha_active_success(self):
        self.user.update(read_dev_agreement=None)
        verify_data = urlencode(
            {
                'secret': '',
                'remoteip': '127.0.0.1',
                'response': 'test',
            }
        )

        responses.add(
            responses.GET,
            'https://www.google.com/recaptcha/api/siteverify?' + verify_data,
            json={'error-codes': [], 'success': True},
        )

        response = self.client.post(
            reverse('devhub.developer_agreement'),
            data={
                'g-recaptcha-response': 'test',
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )

        assert response.status_code == 302
        assert response['Location'] == reverse('devhub.index')
        self.user.reload()
        self.assertCloseToNow(self.user.read_dev_agreement)

    def test_agreement_read_but_too_long_ago(self):
        set_config('last_dev_agreement_change_date', '2018-01-01 12:00')
        before_agreement_last_changed = datetime(2018, 1, 1, 12, 0) - timedelta(days=1)
        self.user.update(read_dev_agreement=before_agreement_last_changed)
        response = self.client.get(reverse('devhub.developer_agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context

    @mock.patch('olympia.users.utils.RestrictionChecker.is_submission_allowed')
    def test_cant_submit_agreement_if_restricted(self, is_submission_allowed_mock):
        is_submission_allowed_mock.return_value = False
        self.user.update(read_dev_agreement=None)
        response = self.client.post(
            reverse('devhub.developer_agreement'),
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        self.user.reload()
        assert self.user.read_dev_agreement is None
        assert is_submission_allowed_mock.call_count == 2
        # First call is from the form, and it's not checking the agreement,
        # it's just to see if the user is restricted.
        assert is_submission_allowed_mock.call_args_list[0] == (
            (),
            {'check_dev_agreement': False},
        )
        # Second call is from the view itself, no arguments
        assert is_submission_allowed_mock.call_args_list[1] == ((), {})

    def test_cant_submit_agreement_if_restricted_functional(self):
        # Like test_cant_submit_agreement_if_restricted() but with no mocks,
        # picking a single restriction and making sure it's working properly.
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        self.user.update(read_dev_agreement=None)
        response = self.client.post(
            reverse('devhub.developer_agreement'),
            data={
                'distribution_agreement': 'on',
                'review_policy': 'on',
            },
        )
        assert response.status_code == 200
        assert response.context['agreement_form'].is_valid() is False
        doc = pq(response.content)
        assert doc('.addon-submission-process').text() == (
            'Multiple submissions violating our policies have been sent '
            'from your location. The IP address has been blocked.\n'
            'More information on Developer Accounts'
        )

    @mock.patch('olympia.users.utils.RestrictionChecker.is_submission_allowed')
    def test_agreement_page_shown_if_restricted(self, is_submission_allowed_mock):
        # Like test_agreement_read() above, but with a restricted user: they
        # are shown the agreement page again instead of redirecting to the
        # api keys page.
        is_submission_allowed_mock.return_value = False
        self.user.update(read_dev_agreement=self.days_ago(0))
        response = self.client.get(reverse('devhub.developer_agreement'))
        assert response.status_code == 200
        assert 'agreement_form' in response.context


class TestAPIKeyPage(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.api_key')
        self.client.force_login_with_2fa(UserProfile.objects.get(email='del@icio.us'))
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.user.update(last_login_ip='192.168.1.1')
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def test_key_redirect(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.api_key'))
        self.assert3xx(
            response,
            '%s%s'
            % (
                reverse('devhub.developer_agreement'),
                '?to=%2Fen-US%2Fdevelopers%2Faddon%2Fapi%2Fkey%2F',
            ),
        )

    def test_redirect_if_restricted(self):
        IPNetworkUserRestriction.objects.create(network='127.0.0.1/32')
        response = self.client.get(reverse('devhub.api_key'))
        self.assert3xx(
            response,
            '%s%s'
            % (
                reverse('devhub.developer_agreement'),
                '?to=%2Fen-US%2Fdevelopers%2Faddon%2Fapi%2Fkey%2F',
            ),
        )

    def test_view_without_credentials_not_confirmed_yet(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        submit = doc('#generate-key')
        assert submit.text() == 'Generate new credentials'
        inputs = doc('.api-input input')
        assert len(inputs) == 0, 'Inputs should be absent before keys exist'
        assert not doc('input[name=confirmation_token]')

    def test_view_with_credentials(self):
        APIKey.objects.create(
            user=self.user,
            type=SYMMETRIC_JWT_TYPE,
            key='some-jwt-key',
            secret='some-jwt-secret',
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        submit = doc('#generate-key')
        assert submit.text() == 'Revoke and regenerate credentials'
        assert doc('#revoke-key').text() == 'Revoke'
        key_input = doc('.key-input input').val()
        assert key_input == 'some-jwt-key'

    def test_view_without_credentials_confirmation_requested_no_token(self):
        APIKeyConfirmation.objects.create(
            user=self.user, token='doesnt matter', confirmed_once=False
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Since confirmation has already been requested, there shouldn't be
        # any buttons on the page if no token was passed in the URL - the user
        # needs to follow the link in the email to continue.
        assert not doc('input[name=confirmation_token]')
        assert not doc('input[name=action]')

    def test_view_without_credentials_confirmation_requested_with_token(self):
        APIKeyConfirmation.objects.create(
            user=self.user, token='secrettoken', confirmed_once=False
        )
        self.url += '?token=secrettoken'
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('input[name=confirmation_token]')) == 1
        token_input = doc('input[name=confirmation_token]')[0]
        assert token_input.value == 'secrettoken'
        submit = doc('#generate-key')
        assert submit.text() == 'Confirm and generate new credentials'

    def test_view_no_credentials_has_been_confirmed_once(self):
        APIKeyConfirmation.objects.create(
            user=self.user, token='doesnt matter', confirmed_once=True
        )
        # Should look similar to when there are no credentials and no
        # confirmation has been requested yet, the post action is where it
        # will differ.
        self.test_view_without_credentials_not_confirmed_yet()

    def test_create_new_credentials_has_been_confirmed_once(self):
        APIKeyConfirmation.objects.create(
            user=self.user, token='doesnt matter', confirmed_once=True
        )
        patch = mock.patch('olympia.devhub.views.APIKey.new_jwt_credentials')
        with patch as mock_creator:
            response = self.client.post(self.url, data={'action': 'generate'})
        mock_creator.assert_called_with(self.user)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.user.email]
        assert message.subject == 'New API key created'
        assert reverse('devhub.api_key') in message.body

        self.assert3xx(response, self.url)

    def test_create_new_credentials_confirming_with_token(self):
        confirmation = APIKeyConfirmation.objects.create(
            user=self.user, token='secrettoken', confirmed_once=False
        )
        patch = mock.patch('olympia.devhub.views.APIKey.new_jwt_credentials')
        with patch as mock_creator:
            response = self.client.post(
                self.url,
                data={'action': 'generate', 'confirmation_token': 'secrettoken'},
            )
        mock_creator.assert_called_with(self.user)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.user.email]
        assert message.subject == 'New API key created'
        assert reverse('devhub.api_key') in message.body

        confirmation.reload()
        assert confirmation.confirmed_once

        self.assert3xx(response, self.url)

    def test_create_new_credentials_not_confirmed_yet(self):
        assert not APIKey.objects.filter(user=self.user).exists()
        assert not APIKeyConfirmation.objects.filter(user=self.user).exists()
        response = self.client.post(self.url, data={'action': 'generate'})
        self.assert3xx(response, self.url)

        # Since there was no credentials are no confirmation yet, this should
        # create a confirmation, send an email with the token, but not create
        # credentials yet.
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [self.user.email]
        assert not APIKey.objects.filter(user=self.user).exists()
        assert APIKeyConfirmation.objects.filter(user=self.user).exists()
        confirmation = APIKeyConfirmation.objects.filter(user=self.user).get()
        assert confirmation.token
        assert not confirmation.confirmed_once
        token = confirmation.token
        expected_url = (
            f'http://testserver/en-US/developers/addon/api/key/?token={token}'
        )
        assert message.subject == 'Confirmation for developer API keys'
        assert expected_url in message.body

    def test_create_new_credentials_confirmation_exists_no_token_passed(self):
        confirmation = APIKeyConfirmation.objects.create(
            user=self.user, token='doesnt matter', confirmed_once=False
        )
        response = self.client.post(self.url, data={'action': 'generate'})
        assert len(mail.outbox) == 0
        assert not APIKey.objects.filter(user=self.user).exists()
        confirmation.reload()
        assert not confirmation.confirmed_once  # Unchanged
        self.assert3xx(response, self.url)

    def test_create_new_credentials_confirmation_exists_token_is_wrong(self):
        confirmation = APIKeyConfirmation.objects.create(
            user=self.user, token='sometoken', confirmed_once=False
        )
        response = self.client.post(
            self.url, data={'action': 'generate', 'confirmation_token': 'wrong'}
        )
        # Nothing should have happened, the user will just be redirect to the
        # page.
        assert len(mail.outbox) == 0
        assert not APIKey.objects.filter(user=self.user).exists()
        confirmation.reload()
        assert not confirmation.confirmed_once
        self.assert3xx(response, self.url)

    def test_delete_and_recreate_credentials_has_been_confirmed_once(self):
        APIKeyConfirmation.objects.create(
            user=self.user, token='doesnt matter', confirmed_once=True
        )
        old_key = APIKey.objects.create(
            user=self.user,
            type=SYMMETRIC_JWT_TYPE,
            key='some-jwt-key',
            secret='some-jwt-secret',
        )
        response = self.client.post(self.url, data={'action': 'generate'})
        self.assert3xx(response, self.url)

        old_key = APIKey.objects.get(pk=old_key.pk)
        assert old_key.is_active is None

        new_key = APIKey.get_jwt_key(user=self.user)
        assert new_key.key != old_key.key
        assert new_key.secret != old_key.secret

    def test_delete_and_recreate_credentials_has_not_been_confirmed_yet(self):
        old_key = APIKey.objects.create(
            user=self.user,
            type=SYMMETRIC_JWT_TYPE,
            key='some-jwt-key',
            secret='some-jwt-secret',
        )
        response = self.client.post(self.url, data={'action': 'generate'})
        self.assert3xx(response, self.url)

        old_key = APIKey.objects.get(pk=old_key.pk)
        assert old_key.is_active is None

        # Since there was no confirmation, this should create a one, send an
        # email with the token, but not create credentials yet. (Would happen
        # for an user that had api keys from before we introduced confirmation
        # mechanism, but decided to regenerate).
        assert len(mail.outbox) == 2  # 2 because of key revocation email.
        assert 'revoked' in mail.outbox[0].body
        message = mail.outbox[1]
        assert message.to == [self.user.email]
        assert not APIKey.objects.filter(user=self.user, is_active=True).exists()
        assert APIKeyConfirmation.objects.filter(user=self.user).exists()
        confirmation = APIKeyConfirmation.objects.filter(user=self.user).get()
        assert confirmation.token
        assert not confirmation.confirmed_once
        token = confirmation.token
        expected_url = (
            f'http://testserver/en-US/developers/addon/api/key/?token={token}'
        )
        assert message.subject == 'Confirmation for developer API keys'
        assert expected_url in message.body

    def test_delete_credentials(self):
        old_key = APIKey.objects.create(
            user=self.user,
            type=SYMMETRIC_JWT_TYPE,
            key='some-jwt-key',
            secret='some-jwt-secret',
        )
        response = self.client.post(self.url, data={'action': 'revoke'})
        self.assert3xx(response, self.url)

        old_key = APIKey.objects.get(pk=old_key.pk)
        assert old_key.is_active is None

        assert len(mail.outbox) == 1
        assert 'revoked' in mail.outbox[0].body

    def test_enforce_2fa(self):
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        expected_location = fxa_login_url(
            config=settings.FXA_CONFIG['default'],
            state=self.client.session['fxa_state'],
            next_path=self.url,
            enforce_2fa=True,
            login_hint=self.user.email,
        )
        self.assert3xx(response, expected_location)


class TestUpload(UploadMixin, TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.force_login(self.user)
        self.url = reverse('devhub.upload')
        self.xpi_path = self.file_path('webextension_no_id.xpi')
        self.create_flag('2fa-enforcement-for-developers-and-special-users')

    def post(self, theme_specific=False, **kwargs):
        data = {
            'upload': open(self.xpi_path, 'rb'),
            'theme_specific': 'True' if theme_specific else 'False',
        }
        return self.client.post(self.url, data, **kwargs)

    def test_login_required(self):
        self.client.logout()
        response = self.post()
        assert response.status_code == 302

    def test_create_fileupload(self):
        self.client.force_login_with_2fa(self.user)
        self.post()

        upload = FileUpload.objects.filter().order_by('-created').first()
        assert 'webextension_no_id.xpi' in upload.name
        assert upload.file_path.endswith('.zip')  # and not .xpi!
        # Can't compare the data bit by bit because we're repacking, look
        # inside to check it contains the same thing.
        manifest_data = json.loads(
            zipfile.ZipFile(upload.file_path).read('manifest.json')
        )
        original_manifest_data = json.loads(
            zipfile.ZipFile(self.xpi_path).read('manifest.json')
        )
        assert manifest_data == original_manifest_data

    def test_fileupload_metadata(self):
        self.client.force_login_with_2fa(self.user)
        self.client.force_login(self.user)
        self.post(REMOTE_ADDR='4.8.15.16.23.42')
        upload = FileUpload.objects.get()
        assert upload.user == self.user
        assert upload.source == amo.UPLOAD_SOURCE_DEVHUB
        assert upload.ip_address == '4.8.15.16.23.42'

    def test_fileupload_validation_not_a_xpi_file(self):
        self.client.force_login_with_2fa(self.user)
        self.xpi_path = get_image_path('animated.png')  # not a xpi file.
        self.post()
        upload = FileUpload.objects.filter().order_by('-created').first()
        assert upload.validation
        validation = json.loads(upload.validation)

        assert not validation['success']
        # The current interface depends on this JSON structure:
        assert validation['errors'] == 1
        assert validation['warnings'] == 0
        assert len(validation['messages'])
        msg = validation['messages'][0]
        assert msg['type'] == 'error'
        assert msg['message'] == (
            'Unsupported file type, please upload a supported file '
            '(.crx, .xpi, .zip).'
        )
        assert not msg['description']

    def test_redirect(self):
        self.client.force_login_with_2fa(self.user)
        response = self.post()
        upload = FileUpload.objects.get()
        assert upload.channel == amo.CHANNEL_LISTED
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        self.assert3xx(response, url)

    def test_not_an_uuid(self):
        url = reverse('devhub.upload_detail', args=['garbage', 'json'])
        response = self.client.get(url)
        assert response.status_code == 404

    @mock.patch('olympia.devhub.tasks.validate')
    def test_upload_unlisted_addon(self, validate_mock):
        """Unlisted addons are validated as "self hosted" addons."""
        self.client.force_login_with_2fa(self.user)
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.url = reverse('devhub.upload_unlisted')
        response = self.post()
        upload = FileUpload.objects.get()
        assert upload.channel == amo.CHANNEL_UNLISTED
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        self.assert3xx(response, url)

    def test_upload_extension_in_theme_specific_flow(self):
        self.url = reverse('devhub.upload_unlisted')
        response = self.post(theme_specific=True)
        assert response.status_code == 400
        assert response.json() == {
            'validation': {
                'errors': 1,
                'warnings': 0,
                'notices': 0,
                'success': False,
                'compatibility_summary': {'notices': 0, 'errors': 0, 'warnings': 0},
                'metadata': {'listed': True},
                'messages': [
                    {
                        'tier': 1,
                        'type': 'error',
                        'id': ['validation', 'messages', ''],
                        'message': (
                            'This add-on is not a theme. Use the <a href="http://test'
                            'server/en-US/developers/addon/submit/upload-unlisted">'
                            'Submit a New Add-on</a> page to submit extensions.'
                        ),
                        'description': [],
                        'compatibility_type': None,
                        'extra': True,
                    }
                ],
                'message_tree': {},
                'ending_tier': 5,
            }
        }

    def test_upload_extension_without_2fa(self):
        self.url = reverse('devhub.upload')
        from olympia.accounts.utils import fxa_login_url
        from olympia.amo.templatetags.jinja_helpers import absolutify

        response = self.post()
        expected_url = absolutify(
            fxa_login_url(
                config=settings.FXA_CONFIG['default'],
                state=self.client.session['fxa_state'],
                next_path=reverse('devhub.submit.upload', args=['listed']),
                enforce_2fa=True,
            )
        )
        assert response.status_code == 400
        assert response.json() == {
            'validation': {
                'errors': 1,
                'warnings': 0,
                'notices': 0,
                'success': False,
                'compatibility_summary': {'notices': 0, 'errors': 0, 'warnings': 0},
                'metadata': {'listed': True},
                'messages': [
                    {
                        'tier': 1,
                        'type': 'error',
                        'id': ['validation', 'messages', ''],
                        'message': (
                            f'<a href="{expected_url}">'
                            'Please add two-factor authentication to your account '
                            'to submit extensions.</a>'
                        ),
                        'description': [],
                        'compatibility_type': None,
                        'extra': True,
                    }
                ],
                'message_tree': {},
                'ending_tier': 5,
            }
        }

    def test_upload_extension_without_2fa_waffle_is_off(self):
        self.create_flag(
            '2fa-enforcement-for-developers-and-special-users', everyone=False
        )
        self.url = reverse('devhub.upload')
        response = self.post()
        upload = FileUpload.objects.get()
        assert upload.channel == amo.CHANNEL_LISTED
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        self.assert3xx(response, url)

    def test_upload_theme_without_2fa(self):
        self.xpi_path = os.path.join(
            settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
        )
        response = self.post(theme_specific=True)
        upload = FileUpload.objects.get()
        assert upload.channel == amo.CHANNEL_LISTED
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        self.assert3xx(response, url)

    def test_upload_for_standalone_validation_without_2fa(self):
        self.url = reverse('devhub.standalone_upload')
        response = self.post()
        upload = FileUpload.objects.get()
        assert upload.channel == amo.CHANNEL_LISTED
        url = reverse('devhub.standalone_upload_detail', args=[upload.uuid.hex])
        self.assert3xx(response, url)


class TestUploadDetail(UploadMixin, TestCase):
    fixtures = ['base/appversion', 'base/users']

    @classmethod
    def setUpTestData(cls):
        versions = {
            '51.0a1',
            amo.DEFAULT_WEBEXT_MIN_VERSION,
            amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID,
            amo.DEFAULT_WEBEXT_MAX_VERSION,
        }
        for version in versions:
            cls.create_appversion('firefox', version)
            cls.create_appversion('android', version)

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.client.force_login(self.user)

    @classmethod
    def create_appversion(cls, application_name, version):
        return AppVersion.objects.create(
            application=amo.APPS[application_name].id, version=version
        )

    def validation_ok(self):
        return {
            'errors': 0,
            'success': True,
            'warnings': 0,
            'notices': 0,
            'message_tree': {},
            'messages': [],
            'rejected': False,
            'metadata': {},
        }

    def upload_dummy_file(self):
        return self.upload_file(get_image_path('animated.png'))

    def upload_file(self, filename):
        path = (
            os.path.join(
                settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons', filename
            )
            if not filename.startswith('/')
            else filename
        )
        with open(path, 'rb') as f:
            data = f.read()
        upload = FileUpload.from_post(
            [data],
            filename=os.path.basename(filename),
            size=42,
            user=self.user,
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        validate(upload)

    def test_detail_json(self):
        self.upload_dummy_file()

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        assert response.status_code == 200
        data = json.loads(force_str(response.content))

        assert data['validation']['errors'] == 1
        assert data['url'] == (
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        assert data['full_report_url'] == (
            reverse('devhub.upload_detail', args=[upload.uuid.hex])
        )

        # We must have tiers
        assert len(data['validation']['messages'])
        msg = data['validation']['messages'][0]
        assert msg['tier'] == 1

    def test_upload_detail_for_version(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        self.upload_dummy_file()

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        assert response.status_code == 200

    def test_upload_detail_for_version_not_an_uuid(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        url = reverse('devhub.upload_detail_for_version', args=[addon.slug, 'garbage'])
        response = self.client.get(url)
        assert response.status_code == 404

    def test_upload_detail_for_version_wrong_user(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        self.upload_dummy_file()
        upload = FileUpload.objects.get()
        self.client.force_login(user_factory())

        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        assert response.status_code == 403

    def test_upload_detail_for_version_unlisted(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory(version_kw={'channel': amo.CHANNEL_UNLISTED})
        addon.addonuser_set.create(user=user)
        self.upload_dummy_file()

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        assert response.status_code == 200

    def test_upload_detail_for_version_deleted(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        addon.delete()
        self.upload_dummy_file()

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        assert response.status_code == 404

    def test_detail_view(self):
        self.upload_dummy_file()
        upload = FileUpload.objects.filter().order_by('-created').first()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex])
        )
        assert response.status_code == 200
        doc = pq(response.content)
        expected = 'Validation Results for animated.png'
        assert doc('header h2').text() == expected

        suite = doc('#addon-validator-suite')
        expected = reverse('devhub.standalone_upload_detail', args=[upload.uuid.hex])
        assert suite.attr('data-validateurl') == expected

    def test_not_an_uuid_standalone_upload_detail(self):
        url = reverse('devhub.standalone_upload_detail', args=['garbage'])
        response = self.client.get(url)
        assert response.status_code == 404

    def test_wrong_user(self):
        self.upload_dummy_file()
        upload = FileUpload.objects.filter().order_by('-created').first()
        self.client.force_login(user_factory())
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex])
        )
        assert response.status_code == 403

        response = self.client.get(
            reverse('devhub.standalone_upload_detail', args=[upload.uuid.hex])
        )
        assert response.status_code == 403

    def test_no_servererror_on_missing_version(self):
        """https://github.com/mozilla/addons-server/issues/3779

        addons-linter adds proper errors when the version is missing
        but we shouldn't fail on that but properly show the validation
        results.
        """
        self.upload_file('valid_webextension_no_version.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        messages = [
            (m['message'], m.get('type') == 'error')
            for m in data['validation']['messages']
        ]
        expected = [
            ('"/" must have required property \'version\'', True),
            ('The version string should be simplified.', True),
        ]
        assert messages == expected

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_not_a_valid_xpi(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file('unopenable.xpi')
        # We never even reach the linter (we can't: because we're repacking
        # zip files, we should raise an error if the zip is invalid before
        # calling the linter, even though the linter has a perfectly good error
        # message for this kind of situation).
        assert not run_addons_linter_mock.called
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        message = [
            (m['message'], m.get('fatal', False))
            for m in data['validation']['messages']
        ]
        # We do raise a specific error message explaining that the archive is
        # not valid instead of a generic exception.
        assert message == [
            ('Invalid or corrupt add-on file.', True),
        ]

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_invalid_zip_file(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(
            '../../../files/fixtures/files/archive-with-invalid-chars-in-filenames.zip'
        )
        # We never even reach the linter (we can't: because we're repacking zip
        # files, we should raise an error if the zip is invalid before calling
        # the linter, even though the linter has a perfectly good error message
        # for this kind of situation).
        assert not run_addons_linter_mock.called
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        message = [
            (m['message'], m.get('fatal', False))
            for m in data['validation']['messages']
        ]
        assert message == [('Invalid file name in archive: path\\to\\file.txt', False)]

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_experiment_xpi_allowed(self, run_addons_linter_mock):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'Experiments:submit')
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(
            '../../../files/fixtures/files/experiment_inside_webextension.xpi'
        )
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_experiment_xpi_not_allowed(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(
            '../../../files/fixtures/files/experiment_inside_webextension.xpi'
        )
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == [
            {
                'tier': 1,
                'message': 'You cannot submit this type of add-on',
                'fatal': True,
                'type': 'error',
            }
        ]

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_restricted_guid_addon_allowed(self, run_addons_linter_mock):
        self.grant_permission(self.user, 'SystemAddon:Submit')
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(self.file_fixture_path('mozilla_guid.xpi'))
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_restricted_guid_addon_not_allowed(self, run_addons_linter_mock):
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(self.file_fixture_path('mozilla_guid.xpi'))
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == [
            {
                'tier': 1,
                'message': (
                    'You cannot submit an add-on using an ID ending with this suffix'
                ),
                'fatal': True,
                'type': 'error',
            }
        ]

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    @mock.patch('olympia.files.utils.get_signer_organizational_unit_name')
    def test_mozilla_signed_allowed(self, get_signer_mock, run_addons_linter_mock):
        self.grant_permission(self.user, 'SystemAddon:Submit')
        run_addons_linter_mock.return_value = self.validation_ok()
        get_signer_mock.return_value = 'Mozilla Extensions'
        self.upload_file(self.file_fixture_path('webextension_signed_already.xpi'))
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == []

    @mock.patch('olympia.files.utils.get_signer_organizational_unit_name')
    def test_mozilla_signed_not_allowed_not_allowed(self, get_signer_mock):
        get_signer_mock.return_value = 'Mozilla Extensions'
        self.upload_file(self.file_fixture_path('webextension_signed_already.xpi'))
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        )
        data = json.loads(force_str(response.content))
        # There should be an error as verified below and a warning about the
        # use of `applications` instead of `browser_specific_settings` (which
        # is now deprecated).
        assert len(data['validation']['messages']) == 2
        assert data['validation']['messages'][0] == {
            'tier': 1,
            'message': 'You cannot submit a Mozilla Signed Extension',
            'fatal': True,
            'type': 'error',
        }

    @mock.patch('olympia.devhub.tasks.run_addons_linter')
    def test_system_addon_update_allowed(self, run_addons_linter_mock):
        """Updates to system addons are allowed from anyone."""
        addon = addon_factory(guid='systemaddon@mozilla.org')
        AddonUser.objects.create(addon=addon, user=self.user)
        run_addons_linter_mock.return_value = self.validation_ok()
        self.upload_file(self.file_fixture_path('mozilla_guid.xpi'))
        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        data = json.loads(force_str(response.content))
        assert data['validation']['messages'] == []

    def test_no_redirect_for_metadata(self):
        addon = addon_factory(status=amo.STATUS_NULL)
        AddonCategory.objects.filter(addon=addon).delete()
        addon.addonuser_set.create(user=self.user)
        self.upload_dummy_file()

        upload = FileUpload.objects.get()
        response = self.client.get(
            reverse(
                'devhub.upload_detail_for_version', args=[addon.slug, upload.uuid.hex]
            )
        )
        assert response.status_code == 200


def assert_json_error(request, field, msg):
    assert request.status_code == 400
    assert request['Content-Type'] == 'application/json'
    field = '__all__' if field is None else field
    content = json.loads(request.content)
    assert field in content, f'{field!r} not in {content!r}'
    assert content[field] == [msg]


def assert_json_field(request, field, msg):
    assert request.status_code == 200
    assert request['Content-Type'] == 'application/json'
    content = json.loads(request.content)
    assert field in content, f'{field!r} not in {content!r}'
    assert content[field] == msg


class TestVersionXSS(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.version = Addon.objects.get(id=3615).current_version
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))

    def test_unique_version_num(self):
        # Can't use a "/" to close the tag, as we're doing a get_url_path on
        # it, which uses addons.versions, which consumes up to the first "/"
        # encountered.
        self.version.update(version='<script>alert("Happy XSS-Xmas");<script>')
        response = self.client.get(reverse('devhub.addons'))
        assert response.status_code == 200
        assert b'<script>alert' not in response.content
        assert b'&lt;script&gt;alert' in response.content


class TestDeleteAddon(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_dev_url('delete')
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))

    def test_bad_password(self):
        response = self.client.post(self.url, {'slug': 'nope'})
        self.assert3xx(response, self.addon.get_dev_url('versions'))
        assert response.context['title'] == (
            'URL name was incorrect. Add-on was not deleted.'
        )
        assert Addon.objects.count() == 1

    def test_success(self):
        response = self.client.post(self.url, {'slug': 'a3615'})
        self.assert3xx(response, reverse('devhub.addons'))
        assert response.context['title'] == 'Add-on deleted.'
        assert Addon.objects.count() == 0


class TestRequestReview(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.redirect_url = self.addon.get_dev_url('versions')
        self.public_url = reverse('devhub.request-review', args=[self.addon.slug])
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)

    def get_version(self):
        return Version.objects.get(pk=self.version.id)

    def check_400(self, url):
        response = self.client.post(url)
        assert response.status_code == 400

    def test_public(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        self.check_400(self.public_url)

    @mock.patch('olympia.addons.models.Addon.has_complete_metadata')
    def test_renominate_for_full_review(self, mock_has_complete_metadata):
        # When a version is rejected, the addon is disabled.
        # The author must upload a new version and re-nominate.
        # Renominating the same version resets the due date.
        mock_has_complete_metadata.return_value = True
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        orig_date = datetime.now() - timedelta(days=30)
        # Pretend it was due in the past:
        self.version.update(due_date=orig_date)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        response = self.client.post(self.public_url)
        self.assert3xx(response, self.redirect_url)
        assert self.get_addon().status == amo.STATUS_NOMINATED
        assert (
            self.get_version().due_date.timetuple()[0:5] != (orig_date.timetuple()[0:5])
        )


class TestRedirects(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.base = reverse('devhub.index')
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))
        self.user = UserProfile.objects.get(email='admin@mozilla.com')
        self.user.update(last_login_ip='192.168.1.1')

    def test_edit(self):
        url = self.base + 'addon/edit/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(response, reverse('devhub.addons.edit', args=['a3615']), 301)

        url = self.base + 'addon/edit/3615/'
        response = self.client.get(url, follow=True)
        self.assert3xx(response, reverse('devhub.addons.edit', args=['a3615']), 301)

    def test_status(self):
        url = self.base + 'addon/status/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(response, reverse('devhub.addons.versions', args=['a3615']), 301)

    def test_versions(self):
        url = self.base + 'versions/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(response, reverse('devhub.addons.versions', args=['a3615']), 301)

    def test_lwt_submit_redirects_to_theme_submit(self):
        url = reverse('devhub.submit.theme.old_lwt_flow')
        response = self.client.get(url, follow=True)
        self.assert3xx(response, reverse('devhub.submit.theme.distribution'), 302)


class TestHasCompleteMetadataRedirects(TestCase):
    """Make sure Addons that are not complete in some way are correctly
    redirected to the right view (and don't end up in a redirect loop)."""

    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = RequestFactory().get('developers/addon/a3615/edit')
        self.request.user = UserProfile.objects.get(email='admin@mozilla.com')
        self.addon = Addon.objects.get(id=3615)
        self.addon.current_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NULL)
        self.addon = Addon.objects.get(id=3615)
        assert self.addon.has_complete_metadata(), self.addon.get_required_metadata()
        assert not self.addon.should_redirect_to_submit_flow()
        # We need to be logged in for any redirection into real views.
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))

    def _test_redirect(self):
        func = dev_required(self.f)
        response = func(self.request, addon_id='a3615')
        assert not self.f.called
        assert response.status_code == 302
        assert response['Location'] == ('/en-US/developers/addon/a3615/submit/details')
        # Check the redirection doesn't redirect also.
        redirection = self.client.get(response['Location'])
        assert redirection.status_code == 200

    def test_default(self):
        func = dev_required(self.f)
        func(self.request, addon_id='a3615')
        # Don't redirect if there is no metadata to collect.
        assert self.f.called

    def test_no_summary(self):
        delete_translation(self.addon, 'summary')
        self._test_redirect()

    def test_no_license(self):
        self.addon.current_version.update(license=None)
        self._test_redirect()

    def test_no_license_no_summary(self):
        self.addon.current_version.update(license=None)
        delete_translation(self.addon, 'summary')
        self._test_redirect()


class TestDocs(TestCase):
    def test_doc_urls(self):
        assert '/en-US/developers/docs/' == reverse('devhub.docs', args=[])
        assert '/en-US/developers/docs/te' == reverse('devhub.docs', args=['te'])
        assert '/en-US/developers/docs/te/st', reverse('devhub.docs', args=['te/st'])

        urls = [
            (reverse('devhub.docs', args=['getting-started']), 301),
            (reverse('devhub.docs', args=['how-to']), 301),
            (reverse('devhub.docs', args=['how-to/other-addons']), 301),
            (reverse('devhub.docs', args=['fake-page']), 404),
            (reverse('devhub.docs', args=['how-to/fake-page']), 404),
            (reverse('devhub.docs'), 301),
        ]

        index = reverse('devhub.index')

        for url in urls:
            response = self.client.get(url[0])
            assert response.status_code == url[1]

            if url[1] == 302:  # Redirect to the index page
                self.assert3xx(response, index)


class TestRemoveLocale(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('devhub.addons.remove-locale', args=['a3615'])
        self.client.force_login(UserProfile.objects.get(email='del@icio.us'))

    def test_bad_request(self):
        response = self.client.post(self.url)
        assert response.status_code == 400

    def test_success(self):
        self.addon.name = {'en-US': 'woo', 'el': 'yeah'}
        self.addon.save()
        self.addon.remove_locale('el')
        qs = Translation.objects.filter(localized_string__isnull=False).values_list(
            'locale', flat=True
        )
        response = self.client.post(self.url, {'locale': 'el'})
        assert response.status_code == 200
        assert sorted(qs.filter(id=self.addon.name_id)) == ['en-US']

    def test_delete_default_locale(self):
        response = self.client.post(self.url, {'locale': self.addon.default_locale})
        assert response.status_code == 400

    def test_remove_version_locale(self):
        version = self.addon.versions.all()[0]
        version.release_notes = {'fr': 'oui'}
        version.save()

        self.client.post(self.url, {'locale': 'fr'})
        res = self.client.get(
            reverse('devhub.versions.edit', args=[self.addon.slug, version.pk])
        )
        doc = pq(res.content)
        # There's 2 fields, one for en-us, one for init.
        assert len(doc('div.trans textarea')) == 2


class TestXssOnAddonName(amo.tests.TestXss):
    def test_devhub_feed_page(self):
        url = reverse('devhub.feed', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_devhub_addon_edit_page(self):
        url = reverse('devhub.addons.edit', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_devhub_version_edit_page(self):
        url = reverse(
            'devhub.versions.edit',
            args=[self.addon.slug, self.addon.current_version.id],
        )
        self.assertNameAndNoXSS(url)

    def test_devhub_version_list_page(self):
        url = reverse('devhub.addons.versions', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)


@pytest.mark.django_db
def test_get_next_version_number():
    addon = addon_factory(version_kw={'version': '1.0'})
    # Easy case - 1.0 to 2.0
    assert get_next_version_number(addon) == '2.0'
    # version numbers without minor numbers should be okay too.
    version_factory(addon=addon, version='2')
    assert get_next_version_number(addon) == '3.0'
    # We just iterate the major version number
    addon.current_version.update(version='34.45.0a1pre')
    addon.current_version.save()
    assert get_next_version_number(addon) == '35.0'
    # "Take" 35.0
    version_factory(
        addon=addon, version='35.0', file_kw={'status': amo.STATUS_DISABLED}
    )
    assert get_next_version_number(addon) == '36.0'
    # And 36.0, even though it's deleted.
    version_factory(addon=addon, version='36.0').delete()
    assert addon.current_version.version == '34.45.0a1pre'
    assert get_next_version_number(addon) == '37.0'


class TestThemeBackgroundImage(TestCase):
    def setUp(self):
        user = user_factory(email='regular@mozilla.com')
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        self.addon = addon_factory(
            users=[user],
            type=amo.ADDON_STATICTHEME,
            file_kw={
                'filename': os.path.join(
                    settings.ROOT, 'src/olympia/devhub/tests/addons/static_theme.zip'
                )
            },
        )
        self.url = reverse(
            'devhub.submit.version.previous_background',
            args=[self.addon.slug, 'listed'],
        )

    def test_wrong_user(self):
        user_factory(email='irregular@mozilla.com')
        self.client.force_login(UserProfile.objects.get(email='irregular@mozilla.com'))
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 403

    def test_no_header_image(self):
        self.addon.current_version.file.update(file='')
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data == {}

    def test_header_image(self):
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        data = json.loads(force_str(response.content))
        assert data
        assert len(data.items()) == 1
        assert 'weta.png' in data
        assert len(data['weta.png']) == 168596  # base64-encoded size


class TestLogout(UserViewBase):
    def test_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.force_login(user)
        assert user.auth_id
        response = self.client.get(reverse('devhub.index'), follow=True)
        assert pq(response.content)('li a.avatar').attr('href') == (user.get_url_path())
        assert pq(response.content)('li a.avatar img').attr('src') == (user.picture_url)

        response = self.client.get('/en-US/developers/logout', follow=False)
        self.assert3xx(response, '/en-US/firefox/', status_code=302)
        response = self.client.get(reverse('devhub.index'), follow=True)
        assert not pq(response.content)('li a.avatar')
        user.reload()
        assert not user.auth_id

    def test_redirect(self):
        self.client.force_login(UserProfile.objects.get(email='jbalogh@mozilla.com'))
        self.client.get(reverse('devhub.index'), follow=True)
        # Just picking a random target URL that works without auth and won't redirect
        # itself.
        url = reverse('version.json')
        response = self.client.get(
            urlparams(reverse('devhub.logout'), to=url), follow=True
        )
        self.assert3xx(response, url, status_code=302)

        # Test an invalid domain
        url = urlparams(
            reverse('devhub.logout'), to='/__version__', domain='http://evil.com'
        )
        response = self.client.get(url, follow=False)
        self.assert3xx(response, '/__version__', status_code=302)

    def test_session_cookie_deleted_on_logout(self):
        self.client.force_login(UserProfile.objects.get(email='jbalogh@mozilla.com'))
        response = self.client.get(reverse('devhub.logout'))
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        cookie_date_string = 'Thu, 01 Jan 1970 00:00:00 GMT'
        assert cookie.value == ''
        # in django2.1+ changed to django.utils.http.http_date from cookie_date
        assert cookie['expires'].replace('-', ' ') == cookie_date_string


class TestStatsLinksInManageMySubmissionsPage(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.addon = addon_factory(users=[self.user])
        self.url = reverse('devhub.addons')
        self.client.force_login(self.user)

    def test_link_to_stats(self):
        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_link_to_stats_for_addon_disabled_by_user(self):
        self.addon.update(disabled_by_user=True)

        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_link_to_stats_for_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)

        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_no_link_for_addon_disabled_by_mozilla(self):
        self.addon.update(status=amo.STATUS_DISABLED)

        self.make_addon_unlisted(self.addon)

        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) not in str(
            response.content
        )

    def test_link_to_stats_for_langpacks(self):
        self.addon.update(type=amo.ADDON_LPAPP)

        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )

    def test_link_to_stats_for_dictionaries(self):
        self.addon.update(type=amo.ADDON_DICT)

        response = self.client.get(self.url)

        assert reverse('stats.overview', args=[self.addon.slug]) in str(
            response.content
        )


@override_switch('suppressed-email', active=True)
class TestVerifyEmail(TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('devhub.email_verification')
        self.user_profile = user_factory()
        self.client.force_login(self.user_profile)

    def with_suppressed_email(self):
        self.suppressed_email = SuppressedEmail.objects.create(
            email=self.user_profile.email
        )

    def with_email_verification(self):
        self.with_suppressed_email()
        self.email_verification = SuppressedEmailVerification.objects.create(
            suppressed_email=self.suppressed_email
        )

    @override_switch('suppressed-email', active=False)
    def test_waffle_switch_disabled(self):
        self.assert3xx(self.client.get(self.url), reverse('devhub.addons'))

    @override_switch('suppressed-email', active=False)
    def test_waffle_switch_disabled_suppressed_email(self):
        self.with_suppressed_email()

        self.assert3xx(self.client.get(self.url), reverse('devhub.addons'))

    @override_switch('suppressed-email', active=False)
    def test_waffle_switch_disabled_email_verification(self):
        self.with_email_verification()

        self.assert3xx(self.client.get(self.url), reverse('devhub.addons'))

    @mock.patch('olympia.devhub.views.send_suppressed_email_confirmation')
    def test_post_existing_verification(self, send_suppressed_email_confirmation_mock):
        self.with_email_verification()
        send_suppressed_email_confirmation_mock.delay.return_value = None
        old_verification = self.email_verification
        response = self.client.post(self.url)

        self.assert3xx(response, reverse('devhub.email_verification'))
        assert self.user_profile.reload().email_verification
        assert not SuppressedEmailVerification.objects.filter(
            pk=old_verification.pk
        ).exists()

    @mock.patch('olympia.devhub.views.send_suppressed_email_confirmation')
    def test_post_new_verification(self, send_suppressed_email_confirmation_mock):
        self.with_suppressed_email()
        send_suppressed_email_confirmation_mock.delay.return_value = None
        response = self.client.post(self.url)

        self.assert3xx(response, reverse('devhub.email_verification'))
        assert self.user_profile.reload().email_verification

    def test_post_already_verified(self):
        response = self.client.post(self.url)

        self.assert3xx(response, reverse('devhub.email_verification'))
        assert not self.user_profile.reload().suppressed_email

    def test_get_hide_suppressed_email_snippet(self):
        """
        on verification page, do not show the suppressed email snippet
        """
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#suppressed-email').length == 0

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_confirmation_complete(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()
        code = self.email_verification.confirmation_code
        url = f'{self.url}?code={code}'

        assert not self.email_verification.is_expired

        response = self.client.get(url)

        assert len(mail.outbox) == 1
        assert 'Your email was successfully verified.' in mail.outbox[0].body
        self.assert3xx(response, reverse('devhub.email_verification'))

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_confirmation_complete_with_timeout(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()
        code = self.email_verification.confirmation_code
        url = f'{self.url}?code={code}'

        assert not self.email_verification.is_expired
        assert not self.email_verification.is_timedout

        with freezegun.freeze_time(self.email_verification.created) as frozen_time:
            frozen_time.tick(timedelta(minutes=10, seconds=1))
            response = self.client.get(url)

            assert len(mail.outbox) == 1
            assert 'Your email was successfully verified.' in mail.outbox[0].body
            self.assert3xx(response, reverse('devhub.email_verification'))

    def test_get_email_verified(self):
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert 'Your email address' in doc.text()

    def test_get_email_suppressed(self):
        self.with_suppressed_email()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert 'Please verify your email' in doc.text()
        assert 'Verify email' in doc.text()

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_verification_expired(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()

        with freezegun.freeze_time(self.email_verification.created) as frozen_time:
            frozen_time.tick(timedelta(days=31))

            self.client.force_login(self.user_profile)
            response = self.client.get(self.url)
            doc = pq(response.content)

            assert 'Could not verify email address.' in doc.text()
            assert 'Send another email' in doc.text()

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_verification_pending_without_emails(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert 'We are sending an email to you' in doc.text()
        assert 'Refresh results' in doc.text()

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_verification_pending_with_emails(self, mock_check_emails):
        mock_check_emails.return_value = [
            {'status': 'Delivered', 'subject': 'subject', 'from': 'from', 'to': 'to'}
        ]
        self.with_email_verification()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert (
            'The table below shows all emails we have attempted to send to you'
        ) in doc.text()
        assert 'Delivered' in doc.text()
        assert 'subject' in doc.text()
        assert 'from' in doc.text()
        assert 'to' in doc.text()
        assert 'Refresh results' in doc.text()

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_verification_timedout(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()

        with freezegun.freeze_time(self.email_verification.created) as frozen_time:
            frozen_time.tick(timedelta(minutes=10, seconds=31))

            assert self.email_verification.is_timedout

            response = self.client.get(self.url)
            doc = pq(response.content)

            assert 'It is taking longer than expected' in doc.text()
            assert 'Send another email' in doc.text()

            assert 'If you encounter issues' in doc.text()
            support_link = doc('a:contains("troubleshooting suggestions")')
            assert (
                '/documentation/publish/developer-accounts/#email-issues'
                '?utm_source=addons.mozilla.org&utm_medium=referral'
                '&utm_content=devhub' in support_link.attr('href')
            )

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_verification_delivered(self, mock_check_suppressed):
        mock_check_suppressed.return_value = []
        self.with_email_verification()
        self.email_verification.status = (
            SuppressedEmailVerification.STATUS_CHOICES.Delivered
        )
        self.email_verification.save()
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert 'An email with a confirmation link has been sent' in doc.text()
        assert 'The table below shows all emails ' not in doc.text()

    @mock.patch('olympia.devhub.views.check_suppressed_email_confirmation')
    def test_get_confirmation_invalid(self, mock_check_emails):
        mock_check_emails.return_value = []
        self.with_email_verification()
        code = 'invalid'
        url = f'{self.url}?code={code}'
        response = self.client.get(url)
        doc = pq(response.content)

        assert (
            'The provided code is invalid, unauthorized, expired or incomplete.'
            in doc.text()
        )
        assert 'Send another email' in doc.text()
