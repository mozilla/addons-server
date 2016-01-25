import re

import mock
from pyquery import PyQuery as pq

from django.core.files import temp

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.tests import formset, initial
from addons.models import Addon, AddonUser
from applications.models import AppVersion
from devhub.models import ActivityLog
from files.models import File
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version


class TestVersion(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestVersion, self).setUp()
        self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = self.get_addon()
        self.version = Version.objects.get(id=81551)
        self.url = self.addon.get_dev_url('versions')

        self.disable_url = self.addon.get_dev_url('disable')
        self.enable_url = self.addon.get_dev_url('enable')
        self.unlist_url = self.addon.get_dev_url('unlist')
        self.delete_url = reverse('devhub.versions.delete', args=['a3615'])
        self.delete_data = {'addon_id': self.addon.pk,
                            'version_id': self.version.pk}

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def get_doc(self):
        res = self.client.get(self.url)
        assert res.status_code == 200
        return pq(res.content)

    def test_version_status_public(self):
        doc = self.get_doc()
        assert doc('.addon-status')

        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled')
        assert doc('.addon-status .status-admin-disabled').text() == 'Disabled by Mozilla'

        self.addon.update(disabled_by_user=False)
        doc = self.get_doc()
        assert doc('.addon-status .status-admin-disabled').text() == 'Disabled by Mozilla'

        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('.addon-status .status-disabled').text() == 'You have disabled this add-on'

    def test_no_validation_results(self):
        doc = self.get_doc()
        v = doc('td.file-validation').text()
        assert re.sub(r'\s+', ' ', v) == 'All Platforms Not validated. Validate now.'
        assert doc('td.file-validation a').attr('href') == reverse('devhub.file_validation', args=[self.addon.slug, self.version.all_files[0].id])

    def test_upload_link_label_in_edit_nav(self):
        url = reverse('devhub.versions.edit',
                      args=(self.addon.slug, self.version.pk))
        r = self.client.get(url)
        doc = pq(r.content)
        assert doc('.addon-status>.addon-upload>strong>a').text() == 'Upload a new file'

    def test_delete_message(self):
        """Make sure we warn our users of the pain they will feel."""
        r = self.client.get(self.url)
        doc = pq(r.content)

        expected = (
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted again by others.'
        )
        assert doc('#modal-delete p').eq(0).text() == expected

    def test_delete_message_if_bits_are_messy(self):
        """Make sure we warn krupas of the pain they will feel."""
        self.addon.highest_status = amo.STATUS_NULL
        self.addon.status = amo.STATUS_UNREVIEWED
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)

        expected = (
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted again by others.'
        )
        assert doc('#modal-delete p').eq(0).text() == expected

    def test_delete_message_incomplete(self):
        """
        If an addon has highest_status = 0, they shouldn't be bothered with a
        blacklisting threat if they hit delete.
        """
        self.addon.highest_status = amo.STATUS_NULL
        self.addon.status = amo.STATUS_NULL
        self.addon.save()
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#modal-delete p.warning').length == 0

    def test_delete_version(self):
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        assert ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id) .count() == 1

    def test_delete_version_then_detail(self):
        version, file = self._extra_version_and_file(amo.STATUS_LITE)
        self.client.post(self.delete_url, self.delete_data)
        res = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        assert res.status_code == 200

    def test_cant_delete_version(self):
        self.client.logout()
        res = self.client.post(self.delete_url, self.delete_data)
        assert res.status_code == 302
        assert Version.objects.filter(pk=81551).exists()

    def test_version_delete_status_null(self):
        res = self.client.post(self.delete_url, self.delete_data)
        assert res.status_code == 302
        assert self.addon.versions.count() == 0
        assert Addon.objects.get(id=3615).status == amo.STATUS_NULL

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

        res = self.client.post(self.delete_url, self.delete_data)
        assert res.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_PUBLIC

    def test_version_delete_status_unreviewd(self):
        self._extra_version_and_file(amo.STATUS_BETA)

        res = self.client.post(self.delete_url, self.delete_data)
        assert res.status_code == 302
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_UNREVIEWED

    @mock.patch('files.models.File.hide_disabled_file')
    def test_user_can_disable_addon(self, hide_mock):
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=False)
        res = self.client.post(self.disable_url)
        assert res.status_code == 302
        addon = Addon.objects.get(id=3615)
        assert addon.disabled_by_user is True
        assert addon.status == amo.STATUS_PUBLIC
        assert hide_mock.called

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.USER_DISABLE.id
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg, ("Unexpected: %r" % msg)

    @mock.patch('devhub.views.unindex_addons')
    def test_user_can_unlist_addon(self, unindex):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=False,
                          is_listed=True)
        res = self.client.post(self.unlist_url)
        assert res.status_code == 302
        addon = Addon.with_unlisted.get(id=3615)
        assert addon.status == amo.STATUS_PUBLIC
        assert not addon.is_listed

        # Make sure we remove the addon from the search index.
        assert unindex.delay.called

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.ADDON_UNLISTED.id
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg

    @mock.patch('devhub.views.unindex_addons')
    def test_user_can_unlist_hidden_addon(self, unindex):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True,
                          is_listed=True)
        res = self.client.post(self.unlist_url)
        assert res.status_code == 302
        addon = Addon.with_unlisted.get(id=3615)
        assert addon.status == amo.STATUS_PUBLIC
        assert not addon.is_listed
        assert not addon.disabled_by_user

        # Make sure we remove the addon from the search index.
        assert unindex.delay.called

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.ADDON_UNLISTED.id
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg

    def test_user_get(self):
        assert self.client.get(self.enable_url).status_code == 405

    def test_user_can_enable_addon(self):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        res = self.client.post(self.enable_url)
        self.assert3xx(res, self.url, 302)
        addon = self.get_addon()
        assert addon.disabled_by_user is False
        assert addon.status == amo.STATUS_PUBLIC

        entry = ActivityLog.objects.get()
        assert entry.action == amo.LOG.USER_ENABLE.id
        msg = entry.to_string()
        assert unicode(self.addon.name) in msg, ("Unexpected: %r" % msg)

    def test_unprivileged_user_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        res = self.client.post(self.disable_url)
        assert res.status_code == 302
        assert Addon.objects.get(id=3615).disabled_by_user is False

    def test_non_owner_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.post(self.disable_url)
        assert res.status_code == 403
        assert Addon.objects.get(id=3615).disabled_by_user is False

    def test_non_owner_cant_enable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.get(self.enable_url)
        assert res.status_code == 403
        assert Addon.objects.get(id=3615).disabled_by_user is False

    def test_non_owner_cant_change_status(self):
        """A non-owner can't use the radio buttons."""
        self.addon.update(disabled_by_user=False)
        addon_user = AddonUser.objects.get(addon=self.addon)
        addon_user.role = amo.AUTHOR_ROLE_VIEWER
        addon_user.save()
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('.enable-addon').attr('checked') == 'checked'
        assert doc('.enable-addon').attr('disabled') == 'disabled'
        assert not doc('.disable-addon').attr('checked')
        assert doc('.disable-addon').attr('disabled') == 'disabled'
        assert not doc('.unlist-addon').attr('checked')
        assert doc('.unlist-addon').attr('disabled') == 'disabled'

    def test_published_addon_radio(self):
        """Published (listed) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('.enable-addon').attr('checked') == 'checked'
        enable_url = self.addon.get_dev_url('enable')
        assert doc('.enable-addon').attr('data-url') == enable_url
        assert not doc('.enable-addon').attr('disabled')
        assert doc('#modal-disable')
        assert doc('#modal-unlist')
        assert not doc('.disable-addon').attr('checked')
        assert not doc('.disable-addon').attr('disabled')
        assert not doc('.unlist-addon').attr('checked')
        assert not doc('.unlist-addon').attr('disabled')

    def test_hidden_addon_radio(self):
        """Hidden (disabled) addon is selected: can hide or publish."""
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('.enable-addon').attr('checked')
        assert not doc('.enable-addon').attr('disabled')
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert not doc('.disable-addon').attr('disabled')
        assert not doc('.unlist-addon').attr('checked')
        assert not doc('.unlist-addon').attr('disabled')
        assert not doc('#modal-disable')
        assert doc('#modal-unlist')

    def test_status_disabled_addon_radio(self):
        """Disabled by Mozilla addon: hidden selected, can't change status."""
        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('.enable-addon').attr('checked')
        assert doc('.enable-addon').attr('disabled') == 'disabled'
        assert doc('.disable-addon').attr('checked') == 'checked'
        assert doc('.disable-addon').attr('disabled') == 'disabled'
        assert not doc('.unlist-addon').attr('checked')
        assert doc('.unlist-addon').attr('disabled') == 'disabled'

    def test_unlisted_addon_cant_change_status(self):
        """Unlisted addon: can't change its status."""
        self.addon.update(disabled_by_user=False, is_listed=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('.enable-addon').attr('checked')
        assert doc('.enable-addon').attr('disabled') == 'disabled'
        assert not doc('.disable-addon').attr('checked')
        assert doc('.disable-addon').attr('disabled') == 'disabled'
        assert doc('.unlist-addon').attr('checked') == 'checked'
        assert not doc('.unlist-addon').attr('disabled')
        assert doc('#modal-disable')
        assert not doc('#modal-unlist')

    def test_cancel_get(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        assert self.client.get(cancel_url).status_code == 405

    def test_cancel_wrong_status(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        for status in Addon.STATUS_CHOICES:
            if status in amo.UNDER_REVIEW_STATUSES + (amo.STATUS_DELETED,):
                continue

            self.addon.update(status=status)
            self.client.post(cancel_url)
            assert Addon.objects.get(id=3615).status == status

    def test_cancel(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.client.post(cancel_url)
        assert Addon.objects.get(id=3615).status == amo.STATUS_LITE

        for status in (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED):
            self.addon.update(status=status)
            self.client.post(cancel_url)
            assert Addon.objects.get(id=3615).status == amo.STATUS_NULL

    def test_not_cancel(self):
        self.client.logout()
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        assert self.addon.status == amo.STATUS_PUBLIC
        res = self.client.post(cancel_url)
        assert res.status_code == 302
        assert Addon.objects.get(id=3615).status == amo.STATUS_PUBLIC

    def test_cancel_button(self):
        for status in Addon.STATUS_CHOICES:
            if status not in amo.UNDER_REVIEW_STATUSES:
                continue

            self.addon.update(status=status)
            res = self.client.get(self.url)
            doc = pq(res.content)
            assert doc('#cancel-review')
            assert doc('#modal-cancel')

    def test_not_cancel_button(self):
        for status in Addon.STATUS_CHOICES:
            if status in amo.UNDER_REVIEW_STATUSES:
                continue

            self.addon.update(status=status)
            res = self.client.get(self.url)
            doc = pq(res.content)
            assert not doc('#cancel-review')
            assert not doc('#modal-cancel')

    def test_purgatory_request_review(self):
        self.addon.update(status=amo.STATUS_PURGATORY)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        assert buttons == 'Request Preliminary Review Request Full Review'

    def test_incomplete_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        assert buttons == 'Request Preliminary Review Request Full Review'

    def test_rejected_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.latest_version.files.update(status=amo.STATUS_DISABLED)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        assert buttons is None

    def test_add_version_modal(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('.supported-platforms input.platform').length == 5
        assert set([i.attrib['type'] for i in doc('input.platform')]) == set(['checkbox'])


class TestVersionEditMixin(object):

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_version(self):
        return self.get_addon().current_version

    def formset(self, *args, **kw):
        defaults = {'approvalnotes': 'xxx'}
        defaults.update(kw)
        return formset(*args, **defaults)


class TestVersionEditBase(TestVersionEditMixin, amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'base/thunderbird']

    def setUp(self):
        super(TestVersionEditBase, self).setUp()
        self.client.login(username='del@icio.us', password='password')
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
        assert sorted(amo.PLATFORMS[p[0]].shortname for p in fld.choices) == ['android']


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
        d = self.formset(releasenotes='xx', approvalnotes='yy')
        r = self.client.post(self.url, d)
        assert r.status_code == 302
        version = self.get_version()
        assert unicode(version.releasenotes) == 'xx'
        assert unicode(version.approvalnotes) == 'yy'

    def test_version_number_redirect(self):
        url = self.url.replace(str(self.version.id), self.version.version)
        r = self.client.get(url, follow=True)
        self.assert3xx(r, self.url)

    def test_supported_platforms(self):
        res = self.client.get(self.url)
        choices = res.context['new_file_form'].fields['platform'].choices
        taken = [f.platform for f in self.version.files.all()]
        platforms = set(self.version.compatible_platforms()) - set(taken)
        assert len(choices) == len(platforms)

    def test_can_upload(self):
        self.version.files.all().delete()
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('a.add-file')

    def test_not_upload(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('a.add-file')

    def test_add(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert res.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app'

    def test_add_not(self):
        for id in [18, 52, 59, 60, 61]:
            av = AppVersion(application=id, version='1')
            av.save()
            ApplicationsVersions(application=id, min=av, max=av,
                                 version=self.version).save()

        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not res.context['compat_form'].extra_forms
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
        assert version.addon.admin_review

        # Check that the corresponding automatic activity log has been created.
        log = ActivityLog.objects.get(action=amo.LOG.REQUEST_SUPER_REVIEW.id)
        assert log.details['comments'] == (
            u'This version has been automatically flagged as admin review, as '
            u'it had some source files attached when submitted.')

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

    def test_dont_reset_admin_review_flag_if_no_new_source(self):
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
            assert version.addon.admin_review

        # Unset the "admin review" flag, and re save the version. It shouldn't
        # reset the flag, as the source hasn't changed.
        version.addon.update(admin_review=False)
        data = self.formset(name='some other name')
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        version = Version.objects.get(pk=self.version.pk)
        assert version.source
        assert not version.addon.admin_review


class TestVersionEditSearchEngine(TestVersionEditMixin,
                                  amo.tests.BaseTestCase):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=605941
    fixtures = ['base/users', 'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        super(TestVersionEditSearchEngine, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])

    def test_search_engine_edit(self):
        dd = self.formset(prefix="files", releasenotes='xx',
                          approvalnotes='yy')

        r = self.client.post(self.url, dd)
        assert r.status_code == 302
        version = Addon.objects.no_cache().get(id=4594).current_version
        assert unicode(version.releasenotes) == 'xx'
        assert unicode(version.approvalnotes) == 'yy'

    def test_no_compat(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc("#id_form-TOTAL_FORMS")

    def test_no_upload(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('a.add-file')

    @mock.patch('versions.models.Version.is_allowed_upload')
    def test_can_upload(self, allowed):
        allowed.return_value = True
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('a.add-file')


class TestVersionEditFiles(TestVersionEditBase):

    def setUp(self):
        super(TestVersionEditFiles, self).setUp()
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        self.compat = initial(f)

    def formset(self, *args, **kw):
        compat = formset(self.compat, initial_count=1)
        compat.update(kw)
        return super(TestVersionEditFiles, self).formset(*args, **compat)

    def test_delete_file(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)
        assert self.version.files.count() == 1
        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[0]['DELETE'] = True
        assert ActivityLog.objects.count() == 0
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert ActivityLog.objects.count() == 2
        log = ActivityLog.objects.order_by('created')[1]
        assert log.to_string() == u'File delicious_bookmarks-2.1.072-fx.xpi deleted' ' from <a href="/en-US/firefox/addon/a3615' '/versions/2.1.072">Version 2.1.072</a> of <a ' 'href="/en-US/firefox/addon/a3615/">Delicious ' 'Bookmarks</a>.'
        assert r.status_code == 302
        assert self.version.files.count() == 0
        r = self.client.get(self.url)
        assert r.status_code == 200

    def test_unique_platforms(self):
        # Move the existing file to Linux.
        f = self.version.files.get()
        f.update(platform=amo.PLATFORM_LINUX.id)
        # And make a new file for Mac.
        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_MAC.id)

        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[1]['platform'] = forms[0]['platform']
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))
        doc = pq(r.content)
        assert doc('#id_files-0-platform')
        assert r.status_code == 200
        assert r.context['file_form'].non_form_errors() == ['A platform can only be chosen once.']

    def test_all_platforms(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        File.objects.create(version=self.version,
                            platform=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        res = self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert res.context['file_form'].non_form_errors()[0] == 'The platform All cannot be combined with specific platforms.'

    def test_all_platforms_and_delete(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        File.objects.create(
            version=self.version, platform=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # A test that we don't check the platform for deleted files.
        forms[1]['DELETE'] = 1
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert self.version.files.count() == 1

    def add_in_bsd(self):
        f = self.version.files.get()
        # The default file is All, which prevents the addition of more files.
        f.update(platform=amo.PLATFORM_MAC.id)
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
        assert File.objects.no_cache().get(pk=bsd.pk).platform == amo.PLATFORM_BSD.id

    def test_all_unsupported_platforms_change(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # Update the file platform to Linux:
        forms[1]['platform'] = amo.PLATFORM_LINUX.id
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        assert File.objects.no_cache().get(pk=bsd.pk).platform == amo.PLATFORM_LINUX.id
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[1])
        assert 'bsd' not in choices, (
            'After changing BSD file to Linux, BSD should no longer be a '
            'platform choice in: %r' % choices)

    def test_add_file_modal(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('.platform ul label').text() == 'Linux Mac OS X Windows'
        assert set([i.attrib['type'] for i in doc('input.platform')]) == set(['radio'])

    def test_mobile_addon_supports_only_mobile_platforms(self):
        for a in self.version.apps.all():
            a.application = amo.ANDROID.id
            a.save()
        self.version.files.all().update(platform=amo.PLATFORM_ANDROID.id)
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[0])
        assert sorted(choices) == sorted([p.shortname for p in amo.MOBILE_PLATFORMS.values()])


class TestPlatformSearch(TestVersionEditMixin, amo.tests.BaseTestCase):
    fixtures = ['base/users', 'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        super(TestPlatformSearch, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
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


class TestVersionEditCompat(TestVersionEditBase):

    def get_form(self, url=None):
        if not url:
            url = self.url
        av = self.version.apps.get()
        assert av.min.version == '2.0'
        assert av.max.version == '4.0'
        f = self.client.get(url).context['compat_form'].initial_forms[0]
        return initial(f)

    def formset(self, *args, **kw):
        defaults = formset(prefix='files')
        defaults.update(kw)
        return super(TestVersionEditCompat, self).formset(*args, **defaults)

    def test_add_appversion(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = self.formset(initial(f), dict(application=18, min=288, max=298),
                         initial_count=1)
        r = self.client.post(self.url, d)
        assert r.status_code == 302
        apps = self.get_version().compatible_apps.keys()
        assert sorted(apps) == sorted([amo.FIREFOX, amo.THUNDERBIRD])
        assert list(ActivityLog.objects.all().values_list('action')) == [(amo.LOG.MAX_APPVERSION_UPDATED.id,)]

    def test_update_appversion(self):
        d = self.get_form()
        d.update(min=self.v1.id, max=self.v5.id)
        r = self.client.post(self.url,
                             self.formset(d, initial_count=1))
        assert r.status_code == 302
        av = self.version.apps.get()
        assert av.min.version == '1.0'
        assert av.max.version == '5.0'
        assert list(ActivityLog.objects.all().values_list('action')) == [(amo.LOG.MAX_APPVERSION_UPDATED.id,)]

    def test_ajax_update_appversion(self):
        url = reverse('devhub.ajax.compat.update',
                      args=['a3615', self.version.id])
        d = self.get_form(url)
        d.update(min=self.v1.id, max=self.v5.id)
        r = self.client.post(url, self.formset(d, initial_count=1))
        assert r.status_code == 200
        av = self.version.apps.get()
        assert av.min.version == '1.0'
        assert av.max.version == '5.0'
        assert list(ActivityLog.objects.all().values_list('action')) == [(amo.LOG.MAX_APPVERSION_UPDATED.id,)]

    def test_delete_appversion(self):
        # Add thunderbird compat so we can delete firefox.
        self.test_add_appversion()
        f = self.client.get(self.url).context['compat_form']
        d = map(initial, f.initial_forms)
        d[0]['DELETE'] = True
        r = self.client.post(self.url, self.formset(*d, initial_count=2))
        assert r.status_code == 302
        apps = self.get_version().compatible_apps.keys()
        assert apps == [amo.THUNDERBIRD]
        assert list(ActivityLog.objects.all().values_list('action')) == [(amo.LOG.MAX_APPVERSION_UPDATED.id,)]

    def test_unique_apps(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        dupe = initial(f)
        del dupe['id']
        d = self.formset(initial(f), dupe, initial_count=1)
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        # Because of how formsets work, the second form is expected to be a
        # tbird version range.  We got an error, so we're good.

    def test_require_appversion(self):
        old_av = self.version.apps.get()
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['DELETE'] = True
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        assert r.status_code == 200
        assert r.context['compat_form'].non_form_errors() == ['Need at least one compatible application.']
        assert self.version.apps.get() == old_av

    def test_proper_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'], d['max'] = d['max'], d['min']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        assert r.status_code == 200
        assert r.context['compat_form'].forms[0].non_field_errors() == ['Invalid version range.']

    def test_same_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'] = d['max']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        assert r.status_code == 302
        av = self.version.apps.all()[0]
        assert av.min == av.max
