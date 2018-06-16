# -*- coding: utf-8 -*-
import datetime
import re

from django.core.files import temp

import mock

from pyquery import PyQuery as pq
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.accounts.views import API_TOKEN_COOKIE
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonReviewerFlags
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, formset, initial, version_factory
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.files.models import File
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, Version


class TestVersion(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestVersion, self).setUp()
        self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = self.get_addon()
        self.version = Version.objects.get(id=81551)
        self.url = self.addon.get_dev_url('versions')

        self.disable_url = self.addon.get_dev_url('disable')
        self.enable_url = self.addon.get_dev_url('enable')
        self.delete_url = reverse('devhub.versions.delete', args=['a3615'])
        self.delete_data = {'addon_id': self.addon.pk,
                            'version_id': self.version.pk}

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def get_doc(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        return pq(response.content)

    def test_version_status_public(self):
        doc = self.get_doc()
        assert doc('.addon-status')

        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled')
        assert doc('.addon-status .status-admin-disabled').text() == (
            'Disabled by Mozilla')

        self.addon.update(disabled_by_user=False)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled').text() == (
            'Disabled by Mozilla')

        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-disabled').text() == (
            'Invisible')

    def test_label_open_marked_safe(self):
        doc = self.get_doc()
        assert '<strong>Visible:</strong>' in doc.html()

        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        doc = self.get_doc()
        assert '<strong>Invisible:</strong>' in doc.html()

    def test_no_validation_results(self):
        doc = self.get_doc()
        v = doc('td.file-validation').text()
        assert re.sub(r'\s+', ' ', v) == (
            'All Platforms Not validated. Validate now.')
        assert doc('td.file-validation a').attr('href') == (
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.version.all_files[0].id]))

    def test_upload_link_label_in_edit_nav(self):
        url = reverse('devhub.versions.edit',
                      args=(self.addon.slug, self.version.pk))
        response = self.client.get(url)
        link = pq(response.content)('.addon-status>.addon-upload>strong>a')
        assert link.text() == 'Upload New Version'
        assert link.attr('href') == (
            reverse('devhub.submit.version', args=[self.addon.slug]))

        # Don't show for STATUS_DISABLED addons.
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(url)
        assert not pq(response.content)('.addon-status>.addon-upload>strong>a')

    def test_delete_message(self):
        """Make sure we warn our users of the pain they will feel."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#modal-delete p').eq(0).text() == (
            'Deleting your add-on will permanently delete all versions and '
            'files you have submitted for this add-on, listed or not. '
            'The add-on ID will continue to be linked to your account, so '
            'others won\'t be able to submit versions using the same ID.')

    def test_delete_message_if_bits_are_messy(self):
        """Make sure we warn krupas of the pain they will feel."""
        self.addon.status = amo.STATUS_NOMINATED
        self.addon.save()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#modal-delete p').eq(0).text() == (
            'Deleting your add-on will permanently delete all versions and '
            'files you have submitted for this add-on, listed or not. '
            'The add-on ID will continue to be linked to your account, so '
            'others won\'t be able to submit versions using the same ID.')

    def test_delete_message_incomplete(self):
        """
        If an addon has status = 0, they shouldn't be bothered with a
        deny list threat if they hit delete.
        """
        # Need to hard delete the version or add-on will be soft-deleted.
        self.addon.current_version.delete(hard=True)
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL
        response = self.client.get(self.url)
        doc = pq(response.content)
        # Normally 2 paragraphs, one is the warning which we should take out.
        assert doc('#modal-delete p.warning').length == 0

    def test_delete_version(self):
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        assert ActivityLog.objects.filter(
            action=amo.LOG.DELETE_VERSION.id).count() == 1

    def test_delete_version_then_detail(self):
        version, file = self._extra_version_and_file(amo.STATUS_PUBLIC)
        self.client.post(self.delete_url, self.delete_data)
        response = self.client.get(
            reverse('addons.detail', args=[self.addon.slug]))
        assert response.status_code == 200

    def test_version_delete_version_deleted(self):
        self.version.delete()
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 404

    def test_cant_delete_version(self):
        self.client.logout()
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert Version.objects.filter(pk=81551).exists()

    def test_version_delete_status_null(self):
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 0
        assert Addon.objects.get(id=3615).status == amo.STATUS_NULL

    def test_disable_version(self):
        self.delete_data['disable_version'] = ''
        self.client.post(self.delete_url, self.delete_data)
        assert Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(
            action=amo.LOG.DELETE_VERSION.id).count() == 0
        assert ActivityLog.objects.filter(
            action=amo.LOG.DISABLE_VERSION.id).count() == 1

    def test_reenable_version(self):
        Version.objects.get(pk=81551).all_files[0].update(
            status=amo.STATUS_DISABLED, original_status=amo.STATUS_PUBLIC)
        self.reenable_url = reverse('devhub.versions.reenable', args=['a3615'])
        response = self.client.post(
            self.reenable_url, self.delete_data, follow=True)
        assert response.status_code == 200
        assert not Version.objects.get(pk=81551).is_user_disabled
        assert ActivityLog.objects.filter(
            action=amo.LOG.ENABLE_VERSION.id).count() == 1

    def test_reenable_deleted_version(self):
        Version.objects.get(pk=81551).delete()
        self.delete_url = reverse('devhub.versions.reenable', args=['a3615'])
        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 404
        assert ActivityLog.objects.filter(
            action=amo.LOG.ENABLE_VERSION.id).count() == 0

    def _extra_version_and_file(self, status):
        version = Version.objects.get(id=81551)

        version_two = Version(addon=self.addon,
                              license=version.license,
                              version='1.2.3')
        version_two.save()

        file_two = File(status=status, version=version_two)
        file_two.save()
        return version_two, file_two

    def test_version_delete_status(self):
        self._extra_version_and_file(amo.STATUS_PUBLIC)

        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_PUBLIC

    def test_version_delete_status_unreviewed(self):
        self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)

        response = self.client.post(self.delete_url, self.delete_data)
        assert response.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_NOMINATED

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_user_can_disable_addon(self, hide_mock):
        version = self.addon.current_version
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=False)
        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        addon = Addon.objects.get(id=3615)
        version.reload()
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_PUBLIC
        assert hide_mock.called

        # Check we didn't change the status of the files.
        assert version.files.all()[0].status == amo.STATUS_PUBLIC

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.USER_DISABLE.id
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg, ("Unexpected: %r" % msg)

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_user_can_disable_addon_pending_version(self, hide_mock):
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=False)
        (new_version, _) = self._extra_version_and_file(
            amo.STATUS_AWAITING_REVIEW)
        assert self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED) == new_version

        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        addon = Addon.objects.get(id=3615)
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_PUBLIC
        assert hide_mock.called

        # Check we disabled the file pending review.
        assert new_version.all_files[0].status == amo.STATUS_DISABLED
        # latest version should be reset when the file/version was disabled.
        assert self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED) != new_version

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.USER_DISABLE.id
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg, ("Unexpected: %r" % msg)

    @mock.patch('olympia.files.models.File.hide_disabled_file')
    def test_disabling_addon_awaiting_review_disables_version(self, hide_mock):
        self.addon.update(status=amo.STATUS_AWAITING_REVIEW,
                          disabled_by_user=False)
        self.version.all_files[0].update(status=amo.STATUS_AWAITING_REVIEW)

        res = self.client.post(self.disable_url)
        assert res.status_code == 302
        addon = Addon.objects.get(id=3615)
        assert addon.disabled_by_user
        assert addon.status == amo.STATUS_NULL
        assert hide_mock.called

        # Check we disabled the file pending review.
        self.version = Version.objects.get(id=self.version.id)
        assert self.version.all_files[0].status == amo.STATUS_DISABLED

    def test_user_get(self):
        assert self.client.get(self.enable_url).status_code == 405

    def test_user_can_enable_addon(self):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        response = self.client.post(self.enable_url)
        self.assert3xx(response, self.url, 302)
        addon = self.get_addon()
        assert not addon.disabled_by_user
        assert addon.status == amo.STATUS_PUBLIC

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.USER_ENABLE.id
        msg = entry.to_string()
        assert unicode(self.addon.name) in msg, ("Unexpected: %r" % msg)

    def test_unprivileged_user_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.post(self.disable_url)
        assert response.status_code == 403
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_enable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.enable_url)
        assert response.status_code == 403
        assert not Addon.objects.get(id=3615).disabled_by_user

    def test_non_owner_cant_change_status(self):
        """A non-owner can't use the radio buttons."""
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_published_addon_radio(self):
        """Published (listed) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.enable-addon').attr('checked') == 'checked'
        enable_url = self.addon.get_dev_url('enable')
        assert doc('.enable-addon').attr('data-url') == enable_url
        assert not doc('.enable-addon').attr('disabled')
        assert doc('#modal-disable')
        assert not doc('.disable-addon').attr('checked')
        assert not doc('.disable-addon').attr('disabled')

    def test_hidden_addon_radio(self):
        """Hidden (disabled) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.enable-addon').attr('checked')
        assert not doc('.enable-addon').attr('disabled')
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert not doc('.disable-addon').attr('disabled')
        assert not doc('#modal-disable')

    def test_status_disabled_addon_radio(self):
        """Disabled by Mozilla addon: hidden selected, can't change status."""
        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=False)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.enable-addon').attr('checked')
        assert doc('.enable-addon').attr('disabled') == 'disabled'
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert doc('.disable-addon').attr('disabled') == 'disabled'

    def test_cancel_get(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        assert self.client.get(cancel_url).status_code == 405

    def test_cancel_wrong_status(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        for status in Addon.STATUS_CHOICES:
            if status in (amo.STATUS_NOMINATED, amo.STATUS_DELETED):
                continue

            self.addon.update(status=status)
            self.client.post(cancel_url)
            assert Addon.objects.get(id=3615).status == status

    def test_cancel(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.client.post(cancel_url)
        assert Addon.objects.get(id=3615).status == amo.STATUS_NULL

    def test_not_cancel(self):
        self.client.logout()
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        assert self.addon.status == amo.STATUS_PUBLIC
        response = self.client.post(cancel_url)
        assert response.status_code == 302
        assert Addon.objects.get(id=3615).status == amo.STATUS_PUBLIC

    def test_cancel_button(self):
        for status in Addon.STATUS_CHOICES:
            if status != amo.STATUS_NOMINATED:
                continue

            self.addon.update(status=status)
            response = self.client.get(self.url)
            doc = pq(response.content)
            assert doc('#cancel-review')
            assert doc('#modal-cancel')

    def test_not_cancel_button(self):
        for status in Addon.STATUS_CHOICES:
            if status == amo.STATUS_NOMINATED:
                continue

            self.addon.update(status=status)
            response = self.client.get(self.url)
            doc = pq(response.content)
            assert not doc('#cancel-review'), status
            assert not doc('#modal-cancel'), status

    def test_incomplete_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        assert buttons == 'Request Review'

    def test_in_submission_can_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        for file_ in latest_version.files.all():
            file_.update(status=amo.STATUS_DISABLED)
        version_factory(addon=self.addon,
                        file_kw={'status': amo.STATUS_DISABLED})
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button')
        # We should only show the links for one of the disabled versions.
        assert buttons.length == 1
        assert buttons.text() == u'Request Review'

    def test_reviewed_cannot_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        for file_ in latest_version.files.all():
            file_.update(reviewed=datetime.datetime.now(),
                         status=amo.STATUS_DISABLED)
        version_factory(addon=self.addon,
                        file_kw={'reviewed': datetime.datetime.now(),
                                 'status': amo.STATUS_DISABLED})
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button')
        # We should only show the links for one of the disabled versions.
        assert buttons.length == 0

    def test_version_history(self):
        self.client.cookies[API_TOKEN_COOKIE] = 'magicbeans'
        v1 = self.version
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        show_links = doc('.review-history-show')
        assert show_links.length == 3
        assert show_links[0].attrib['data-div'] == '#%s-review-history' % v1.id
        assert not show_links[1].attrib.get('data-div')
        assert show_links[2].attrib['data-div'] == '#%s-review-history' % v2.id

        # All 3 links will have a 'data-version' attribute.
        assert show_links[0].attrib['data-version'] == str(v1.id)
        # But the 2nd link will point to the latest version in the channel.
        assert show_links[1].attrib['data-version'] == str(v2.id)
        assert show_links[2].attrib['data-version'] == str(v2.id)

        # Test review history
        review_history_td = doc('#%s-review-history' % v1.id)[0]
        assert review_history_td.attrib['data-token'] == 'magicbeans'
        api_url = absolutify(drf_reverse(
            'version-reviewnotes-list',
            args=[self.addon.id, self.version.id]))
        assert review_history_td.attrib['data-api-url'] == api_url
        assert doc('.review-history-hide').length == 2

        pending_activity_count = doc('.review-history-pending-count')
        # No counter, because we don't have any pending activity to show.
        assert pending_activity_count.length == 0

        # Reply box div is there (only one)
        assert doc('.dev-review-reply-form').length == 1
        review_form = doc('.dev-review-reply-form')[0]
        review_form.attrib['action'] == api_url
        review_form.attrib['data-token'] == 'magicbeans'
        review_form.attrib['data-history'] == '#%s-review-history' % v2.id

    def test_version_history_mixed_channels(self):
        v1 = self.version
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)
        v2.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Should be 2 reply boxes, one for each channel
        assert doc('.dev-review-reply-form').length == 2
        doc('.dev-review-reply-form')[0].attrib['data-history'] == (
            '#%s-review-history' % v1.id)
        doc('.dev-review-reply-form')[1].attrib['data-history'] == (
            '#%s-review-history' % v2.id)

    def test_pending_activity_count(self):
        v2, _ = self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)
        # Add some activity log messages
        ActivityLog.create(amo.LOG.REQUEST_INFORMATION, v2.addon, v2,
                           user=self.user)
        ActivityLog.create(amo.LOG.REQUEST_INFORMATION, v2.addon, v2,
                           user=self.user)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Two versions, but three review-history-show because one reply link.
        assert doc('.review-history-show').length == 3
        # Two versions, but only one counter, for the latest/deleted version
        pending_activity_count = doc('.review-history-pending-count')
        assert pending_activity_count.length == 1
        # There are two activity logs pending
        assert pending_activity_count.text() == '2'

    def test_channel_tag(self):
        self.addon.current_version.update(created=self.days_ago(1))
        v2, _ = self._extra_version_and_file(amo.STATUS_DISABLED)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_LISTED)
        self.addon.update_version()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('td.file-status').length == 2
        # No tag shown because all listed versions
        assert doc('span.distribution-tag-listed').length == 0
        assert doc('span.distribution-tag-unlisted').length == 0

        # Make all the versions unlisted.
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update_version()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('td.file-status').length == 2
        # No tag shown because all unlisted versions
        assert doc('span.distribution-tag-listed').length == 0
        assert doc('span.distribution-tag-unlisted').length == 0

        # Make one of the versions listed.
        v2.update(channel=amo.RELEASE_CHANNEL_LISTED)
        v2.all_files[0].update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        file_status_tds = doc('td.file-status')
        assert file_status_tds.length == 2
        # Tag for channels are shown because both listed and unlisted versions.
        assert file_status_tds('span.distribution-tag-listed').length == 1
        assert file_status_tds('span.distribution-tag-unlisted').length == 1
        # Extra tags in the headers too
        assert doc('h3 span.distribution-tag-listed').length == 2


class TestVersionEditMixin(object):

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_version(self):
        return self.get_addon().current_version

    def formset(self, *args, **kw):
        return formset(*args, **kw)


class TestVersionEditBase(TestVersionEditMixin, TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'base/thunderbird']

    def setUp(self):
        super(TestVersionEditBase, self).setUp()
        self.client.login(email='del@icio.us')
        self.addon = self.get_addon()
        self.version = self.get_version()
        self.url = reverse('devhub.versions.edit',
                           args=['a3615', self.version.id])
        self.v1, _created = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='1.0')
        self.v5, _created = AppVersion.objects.get_or_create(
            application=amo.FIREFOX.id, version='5.0')


class TestVersionEditMobile(TestVersionEditBase):

    def setUp(self):
        super(TestVersionEditMobile, self).setUp()
        self.version.apps.all().delete()
        app_vr = AppVersion.objects.create(application=amo.ANDROID.id,
                                           version='1.0')
        ApplicationsVersions.objects.create(version=self.version,
                                            application=amo.ANDROID.id,
                                            min=app_vr, max=app_vr)
        self.version.files.update(platform=amo.PLATFORM_ANDROID.id)

    def test_mobile_platform_options(self):
        ctx = self.client.get(self.url).context
        fld = ctx['file_form'].forms[0]['platform'].field
        assert sorted(amo.PLATFORMS[p[0]].shortname for p in fld.choices) == (
            ['android'])


class TestVersionEditDetails(TestVersionEditBase):

    def setUp(self):
        super(TestVersionEditDetails, self).setUp()
        ctx = self.client.get(self.url).context
        compat = initial(ctx['compat_form'].forms[0])
        files = initial(ctx['file_form'].forms[0])
        self.initial = formset(compat, **formset(files, prefix='files'))

    def formset(self, *args, **kw):
        defaults = dict(self.initial)
        defaults.update(kw)
        return super(TestVersionEditDetails, self).formset(*args, **defaults)

    def test_edit_notes(self):
        data = self.formset(releasenotes='xx', approvalnotes='yy')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = self.get_version()
        assert unicode(version.releasenotes) == 'xx'
        assert unicode(version.approvalnotes) == 'yy'

    def test_version_number_redirect(self):
        url = self.url.replace(str(self.version.id), self.version.version)
        response = self.client.get(url, follow=True)
        self.assert3xx(response, self.url)

    def test_version_deleted(self):
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

        data = self.formset(releasenotes='xx', approvalnotes='yy')
        response = self.client.post(self.url, data)
        assert response.status_code == 404

    def test_can_upload(self):
        self.version.files.all().delete()
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.add-file')

    def test_not_upload(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.add-file')
        # Make sure the files form is present.
        assert doc('#id_files-0-id').val() == str(
            self.version.files.all()[0].pk)

    def test_add(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert response.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app'

    def test_add_not(self):
        for id in [18, 52, 59, 60, 61]:
            av = AppVersion(application=id, version='1')
            av.save()
            ApplicationsVersions(application=id, min=av, max=av,
                                 version=self.version).save()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not response.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app hide'

    def test_should_accept_zip_source_file(self):
        tdir = temp.gettempdir()
        tmp_file = temp.NamedTemporaryFile
        with tmp_file(suffix=".zip", dir=tdir) as source_file:
            source_file.write('a' * (2 ** 21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = Version.objects.get(pk=self.version.pk)
        assert version.source
        assert version.addon.needs_admin_code_review

        # Check that the corresponding automatic activity log has been created.
        log = ActivityLog.objects.get(action=amo.LOG.SOURCE_CODE_UPLOADED.id)
        assert log

    def test_should_not_accept_exe_source_file(self):
        tdir = temp.gettempdir()
        tmp_file = temp.NamedTemporaryFile
        with tmp_file(suffix=".exe", dir=tdir) as source_file:
            source_file.write('a' * (2 ** 21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
            assert response.status_code == 200
            assert not Version.objects.get(pk=self.version.pk).source

    def test_dont_reset_needs_admin_code_review_flag_if_no_new_source(self):
        tdir = temp.gettempdir()
        tmp_file = temp.NamedTemporaryFile
        with tmp_file(suffix=".zip", dir=tdir) as source_file:
            source_file.write('a' * (2 ** 21))
            source_file.seek(0)
            data = self.formset(source=source_file)
            response = self.client.post(self.url, data)
            assert response.status_code == 302
            version = Version.objects.get(pk=self.version.pk)
            assert version.source
            assert version.addon.needs_admin_code_review

        # Unset the "admin review" flag, and re save the version. It shouldn't
        # reset the flag, as the source hasn't changed.
        AddonReviewerFlags.objects.get(addon=version.addon).update(
            needs_admin_code_review=False)
        data = self.formset(name='some other name')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = Version.objects.get(pk=self.version.pk)
        assert version.source
        assert not version.addon.needs_admin_code_review

    def test_show_request_for_information(self):
        self.user = UserProfile.objects.latest('pk')
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=self.days_ago(2))
        ActivityLog.create(
            amo.LOG.REVIEWER_REPLY_VERSION, self.addon, self.version,
            user=self.user, details={'comments': 'this should not be shown'})
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, self.addon, self.version,
            user=self.user, details={'comments': 'this is an info request'})
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'this should not be shown' not in response.content
        assert 'this is an info request' in response.content

    def test_dont_show_request_for_information_if_none_pending(self):
        self.user = UserProfile.objects.latest('pk')
        ActivityLog.create(
            amo.LOG.REVIEWER_REPLY_VERSION, self.addon, self.version,
            user=self.user, details={'comments': 'this should not be shown'})
        ActivityLog.create(
            amo.LOG.REQUEST_INFORMATION, self.addon, self.version,
            user=self.user, details={'comments': 'this is an info request'})
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'this should not be shown' not in response.content
        assert 'this is an info request' not in response.content

    def test_clear_request_for_information(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=self.days_ago(2))
        response = self.client.post(
            self.url, self.formset(clear_pending_info_request=True))
        assert response.status_code == 302
        flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert flags.pending_info_request is None

    def test_dont_clear_request_for_information(self):
        past_date = self.days_ago(2)
        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=past_date)
        response = self.client.post(self.url, self.formset())
        assert response.status_code == 302
        flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert flags.pending_info_request == past_date


class TestVersionEditSearchEngine(TestVersionEditMixin, TestCase):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=605941
    fixtures = ['base/users', 'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        super(TestVersionEditSearchEngine, self).setUp()
        self.client.login(email='admin@mozilla.com')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])

    def test_search_engine_edit(self):
        dd = self.formset(prefix="files", releasenotes='xx',
                          approvalnotes='yy')

        response = self.client.post(self.url, dd)
        assert response.status_code == 302
        version = Addon.objects.no_cache().get(id=4594).current_version
        assert unicode(version.releasenotes) == 'xx'
        assert unicode(version.approvalnotes) == 'yy'

    def test_no_compat(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc("#id_form-TOTAL_FORMS")

    def test_no_upload(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('a.add-file')

    @mock.patch('olympia.versions.models.Version.is_allowed_upload')
    def test_can_upload(self, allowed):
        allowed.return_value = True
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('a.add-file')


class TestVersionEditFiles(TestVersionEditBase):

    def setUp(self):
        super(TestVersionEditFiles, self).setUp()
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        self.compat = initial(form)

    def formset(self, *args, **kw):
        compat = formset(self.compat, initial_count=1)
        compat.update(kw)
        return super(TestVersionEditFiles, self).formset(*args, **compat)

    def test_unique_platforms(self):
        # Move the existing file to Linux.
        file_ = self.version.files.get()
        file_.update(platform=amo.PLATFORM_LINUX.id)
        # And make a new file for Mac.
        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_MAC.id)

        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[1]['platform'] = forms[0]['platform']
        response = self.client.post(
            self.url, self.formset(*forms, prefix='files'))
        doc = pq(response.content)
        assert doc('#id_files-0-platform')
        assert response.status_code == 200
        assert response.context['file_form'].non_form_errors() == (
            ['A platform can only be chosen once.'])

    def test_all_platforms(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_AWAITING_REVIEW)

        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        response = self.client.post(
            self.url, self.formset(*forms, prefix='files'))
        assert response.context['file_form'].non_form_errors()[0] == (
            'The platform All cannot be combined with specific platforms.')

    def add_in_bsd(self):
        file_ = self.version.files.get()
        # The default file is All, which prevents the addition of more files.
        file_.update(platform=amo.PLATFORM_MAC.id)
        return File.objects.create(version=self.version,
                                   platform=amo.PLATFORM_BSD.id)

    def get_platforms(self, form):
        return [amo.PLATFORMS[i[0]].shortname
                for i in form.fields['platform'].choices]

    # The unsupported platform tests are for legacy addons.  We don't
    # want new addons uploaded with unsupported platforms but the old files can
    # still be edited.

    def test_all_unsupported_platforms(self):
        self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[1])
        assert 'bsd' in choices, (
            'After adding a BSD file, expected its platform to be '
            'available  in: %r' % choices)

    def test_all_unsupported_platforms_unchange(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert File.objects.no_cache().get(pk=bsd.pk).platform == (
            amo.PLATFORM_BSD.id)

    def test_all_unsupported_platforms_change(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # Update the file platform to Linux:
        forms[1]['platform'] = amo.PLATFORM_LINUX.id
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert File.objects.no_cache().get(pk=bsd.pk).platform == (
            amo.PLATFORM_LINUX.id)
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[1])
        assert 'bsd' not in choices, (
            'After changing BSD file to Linux, BSD should no longer be a '
            'platform choice in: %r' % choices)

    def test_mobile_addon_supports_only_mobile_platforms(self):
        for a in self.version.apps.all():
            a.application = amo.ANDROID.id
            a.save()
        self.version.files.all().update(platform=amo.PLATFORM_ANDROID.id)
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[0])
        assert sorted(choices) == (
            sorted([p.shortname for p in amo.MOBILE_PLATFORMS.values()]))


class TestPlatformSearchEngine(TestVersionEditMixin, TestCase):
    fixtures = ['base/users', 'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        super(TestPlatformSearchEngine, self).setUp()
        self.client.login(email='admin@mozilla.com')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])
        self.version = Version.objects.get(id=42352)
        self.file = self.version.files.all()[0]

    def test_no_platform_search_engine(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('#id_files-0-platform')

    def test_changing_platform_search_engine(self):
        dd = self.formset({'id': int(self.file.pk),
                           'platform': amo.PLATFORM_LINUX.id},
                          prefix='files', releasenotes='xx',
                          approvalnotes='yy')
        response = self.client.post(self.url, dd)
        assert response.status_code == 302
        file_ = Version.objects.no_cache().get(id=42352).files.all()[0]
        assert amo.PLATFORM_ALL.id == file_.platform


class TestPlatformStaticTheme(TestVersionEditMixin, TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        self.get_addon().update(type=amo.ADDON_STATICTHEME)
        super(TestPlatformStaticTheme, self).setUp()
        self.client.login(email='admin@mozilla.com')
        self.version = self.get_version()
        self.file = self.version.files.all()[0]
        self.url = reverse('devhub.versions.edit',
                           args=[self.version.addon.slug, self.version.id])

    def formset(self, *args, **kw):
        defaults = dict(self.initial)
        defaults.update(kw)
        return super(TestPlatformStaticTheme, self).formset(*args, **defaults)

    def test_no_platform_selector(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('#id_files-0-platform')

    def test_no_changing_platform(self):
        ctx = self.client.get(self.url).context
        compat = initial(ctx['compat_form'].forms[0])
        files = initial(ctx['file_form'].forms[0])
        files['platform'] = amo.PLATFORM_LINUX.id
        self.initial = formset(compat, **formset(files, prefix='files'))
        response = self.client.post(self.url, self.formset())
        assert response.status_code == 302
        file_ = self.get_version().files.all()[0]
        assert amo.PLATFORM_ALL.id == file_.platform


class TestVersionEditCompat(TestVersionEditBase):

    def get_form(self, url=None):
        if not url:
            url = self.url
        av = self.version.apps.get()
        assert av.min.version == '2.0'
        assert av.max.version == '4.0'
        form = self.client.get(url).context['compat_form'].initial_forms[0]
        return initial(form)

    def formset(self, *args, **kw):
        defaults = formset(prefix='files')
        defaults.update(kw)
        return super(TestVersionEditCompat, self).formset(*args, **defaults)

    def test_add_appversion(self):
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        data = self.formset(
            initial(form), {'application': 18, 'min': 288, 'max': 298},
            initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        apps = self.get_version().compatible_apps.keys()
        assert sorted(apps) == sorted([amo.FIREFOX, amo.THUNDERBIRD])
        assert list(ActivityLog.objects.all().values_list('action')) == (
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_update_appversion(self):
        data = self.get_form()
        data.update(min=self.v1.id, max=self.v5.id)
        response = self.client.post(
            self.url, self.formset(data, initial_count=1))
        assert response.status_code == 302
        av = self.version.apps.get()
        assert av.min.version == '1.0'
        assert av.max.version == '5.0'
        assert list(ActivityLog.objects.all().values_list('action')) == (
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_ajax_update_appversion(self):
        url = reverse('devhub.ajax.compat.update',
                      args=['a3615', self.version.id])
        data = self.get_form(url)
        data.update(min=self.v1.id, max=self.v5.id)
        response = self.client.post(url, self.formset(data, initial_count=1))
        assert response.status_code == 200
        av = self.version.apps.get()
        assert av.min.version == '1.0'
        assert av.max.version == '5.0'
        assert list(ActivityLog.objects.all().values_list('action')) == (
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_ajax_update_on_deleted_version(self):
        url = reverse('devhub.ajax.compat.update',
                      args=['a3615', self.version.id])
        data = self.get_form(url)
        data.update(min=self.v1.id, max=self.v5.id)
        self.version.delete()
        response = self.client.post(url, self.formset(data, initial_count=1))
        assert response.status_code == 404

    def test_delete_appversion(self):
        # Add thunderbird compat so we can delete firefox.
        self.test_add_appversion()
        form = self.client.get(self.url).context['compat_form']
        data = map(initial, form.initial_forms)
        data[0]['DELETE'] = True
        response = self.client.post(
            self.url, self.formset(*data, initial_count=2))
        assert response.status_code == 302
        apps = self.get_version().compatible_apps.keys()
        assert apps == [amo.THUNDERBIRD]
        assert list(ActivityLog.objects.all().values_list('action')) == (
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_unique_apps(self):
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        dupe = initial(form)
        del dupe['id']
        data = self.formset(initial(form), dupe, initial_count=1)
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        # Because of how formsets work, the second form is expected to be a
        # tbird version range.  We got an error, so we're good.

    def test_require_appversion(self):
        old_av = self.version.apps.get()
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['DELETE'] = True
        response = self.client.post(
            self.url, self.formset(data, initial_count=1))
        assert response.status_code == 200
        assert response.context['compat_form'].non_form_errors() == (
            ['Need at least one compatible application.'])
        assert self.version.apps.get() == old_av

    def test_proper_min_max(self):
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['min'], data['max'] = data['max'], data['min']
        response = self.client.post(
            self.url, self.formset(data, initial_count=1))
        assert response.status_code == 200
        assert response.context['compat_form'].forms[0].non_field_errors() == (
            ['Invalid version range.'])

    def test_same_min_max(self):
        form = self.client.get(
            self.url).context['compat_form'].initial_forms[0]
        data = initial(form)
        data['min'] = data['max']
        response = self.client.post(
            self.url, self.formset(data, initial_count=1))
        assert response.status_code == 302
        av = self.version.apps.all()[0]
        assert av.min == av.max
