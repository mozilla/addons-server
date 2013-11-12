import re
from datetime import datetime, timedelta

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.urlresolvers import reverse
from amo.tests import formset, initial
from addons.models import Addon
from applications.models import Application, AppVersion
from devhub.models import ActivityLog
from files.models import File, Platform
from users.models import UserProfile
from versions.models import ApplicationsVersions, Version


class TestVersion(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
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
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        return pq(res.content)

    def test_version_status_public(self):
        doc = self.get_doc()
        assert doc('#version-status')

        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=True)
        doc = self.get_doc()
        assert doc('#version-status .status-admin-disabled')
        eq_(doc('#version-status strong').text(),
            'This add-on has been disabled by Mozilla .')

        self.addon.update(disabled_by_user=False)
        doc = self.get_doc()
        eq_(doc('#version-status strong').text(),
            'This add-on has been disabled by Mozilla .')

        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        doc = self.get_doc()
        eq_(doc('#version-status strong').text(),
            'You have disabled this add-on.')

    def test_no_validation_results(self):
        doc = self.get_doc()
        v = doc('td.file-validation').text()
        eq_(re.sub(r'\s+', ' ', v),
            'All Platforms Not validated. Validate now.')
        eq_(doc('td.file-validation a').attr('href'),
            reverse('devhub.file_validation',
                    args=[self.addon.slug, self.version.all_files[0].id]))

    def test_delete_message(self):
        """Make sure we warn our users of the pain they will feel."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#modal-delete p').eq(0).text(),
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted ever again, even by '
            'you. The existing users of your add-on will remain on this '
            'update channel and never receive updates again.')

    def test_delete_message_if_bits_are_messy(self):
        """Make sure we warn krupas of the pain they will feel."""
        self.addon.highest_status = amo.STATUS_NULL
        self.addon.status = amo.STATUS_UNREVIEWED
        self.addon.save()

        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#modal-delete p').eq(0).text(),
            'Deleting your add-on will permanently remove it from the site '
            'and prevent its GUID from being submitted ever again, even by '
            'you. The existing users of your add-on will remain on this '
            'update channel and never receive updates again.')

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
        # Normally 2 paragraphs, one is the warning which we should take out.
        eq_(doc('#modal-delete p.warning').length, 0)

    def test_delete_version(self):
        self.client.post(self.delete_url, self.delete_data)
        assert not Version.objects.filter(pk=81551).exists()
        eq_(ActivityLog.objects.filter(action=amo.LOG.DELETE_VERSION.id)
            .count(), 1)

    def test_delete_version_then_detail(self):
        version, file = self._extra_version_and_file(amo.STATUS_LITE)
        self.client.post(self.delete_url, self.delete_data)
        res = self.client.get(reverse('addons.detail', args=[self.addon.slug]))
        eq_(res.status_code, 200)

    def test_cant_delete_version(self):
        self.client.logout()
        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        assert Version.objects.filter(pk=81551).exists()

    def test_version_delete_status_null(self):
        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 0)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_NULL)

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
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_PUBLIC)

    def test_version_delete_status_unreviewd(self):
        self._extra_version_and_file(amo.STATUS_BETA)

        res = self.client.post(self.delete_url, self.delete_data)
        eq_(res.status_code, 302)
        eq_(self.addon.versions.count(), 1)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_UNREVIEWED)

    @mock.patch('files.models.File.hide_disabled_file')
    def test_user_can_disable_addon(self, hide_mock):
        self.addon.update(status=amo.STATUS_PUBLIC,
                          disabled_by_user=False)
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 302)
        addon = Addon.objects.get(id=3615)
        eq_(addon.disabled_by_user, True)
        eq_(addon.status, amo.STATUS_PUBLIC)
        assert hide_mock.called

        entry = ActivityLog.objects.get()
        eq_(entry.action, amo.LOG.USER_DISABLE.id)
        msg = entry.to_string()
        assert self.addon.name.__unicode__() in msg, ("Unexpected: %r" % msg)

    def test_user_get(self):
        eq_(self.client.get(self.enable_url).status_code, 405)

    def test_user_can_enable_addon(self):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        res = self.client.post(self.enable_url)
        self.assertRedirects(res, self.url, 302)
        addon = self.get_addon()
        eq_(addon.disabled_by_user, False)
        eq_(addon.status, amo.STATUS_PUBLIC)

        entry = ActivityLog.objects.get()
        eq_(entry.action, amo.LOG.USER_ENABLE.id)
        msg = entry.to_string()
        assert unicode(self.addon.name) in msg, ("Unexpected: %r" % msg)

    def test_unprivileged_user_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 302)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_non_owner_cant_disable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.post(self.disable_url)
        eq_(res.status_code, 403)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_non_owner_cant_enable_addon(self):
        self.addon.update(disabled_by_user=False)
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.get(self.enable_url)
        eq_(res.status_code, 403)
        eq_(Addon.objects.get(id=3615).disabled_by_user, False)

    def test_show_disable_button(self):
        self.addon.update(disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('#modal-disable')
        assert doc('#disable-addon')
        assert not doc('#enable-addon')

    def test_not_show_disable(self):
        self.addon.update(status=amo.STATUS_DISABLED, disabled_by_user=False)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not doc('#modal-disable')
        assert not doc('#disable-addon')

    def test_show_enable_button(self):
        self.addon.update(disabled_by_user=True)
        res = self.client.get(self.url)
        doc = pq(res.content)
        a = doc('#enable-addon')
        assert a, "Expected Enable addon link"
        eq_(a.attr('href'), self.enable_url)
        assert not doc('#modal-disable')
        assert not doc('#disable-addon')

    def test_cancel_get(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        eq_(self.client.get(cancel_url).status_code, 405)

    def test_cancel_wrong_status(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        for status in amo.STATUS_CHOICES:
            if status in amo.STATUS_UNDER_REVIEW + (amo.STATUS_DELETED,):
                continue

            self.addon.update(status=status)
            self.client.post(cancel_url)
            eq_(Addon.objects.get(id=3615).status, status)

    def test_cancel(self):
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.client.post(cancel_url)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_LITE)

        for status in (amo.STATUS_UNREVIEWED, amo.STATUS_NOMINATED):
            self.addon.update(status=status)
            self.client.post(cancel_url)
            eq_(Addon.objects.get(id=3615).status, amo.STATUS_NULL)

    def test_not_cancel(self):
        self.client.logout()
        cancel_url = reverse('devhub.addons.cancel', args=['a3615'])
        eq_(self.addon.status, amo.STATUS_PUBLIC)
        res = self.client.post(cancel_url)
        eq_(res.status_code, 302)
        eq_(Addon.objects.get(id=3615).status, amo.STATUS_PUBLIC)

    def test_cancel_button(self):
        for status in amo.STATUS_CHOICES:
            if status not in amo.STATUS_UNDER_REVIEW:
                continue

            self.addon.update(status=status)
            res = self.client.get(self.url)
            doc = pq(res.content)
            assert doc('#cancel-review')
            assert doc('#modal-cancel')

    def test_not_cancel_button(self):
        for status in amo.STATUS_CHOICES:
            if status in amo.STATUS_UNDER_REVIEW:
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
        eq_(buttons, 'Request Preliminary Review Request Full Review')

    def test_incomplete_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        eq_(buttons, 'Request Preliminary Review Request Full Review')

    def test_rejected_request_review(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.latest_version.files.update(status=amo.STATUS_DISABLED)
        doc = pq(self.client.get(self.url).content)
        buttons = doc('.version-status-actions form button').text()
        eq_(buttons, None)

    def test_days_until_full_nomination(self):
        f = File.objects.create(status=amo.STATUS_LITE, version=self.version)
        f.update(datestatuschanged=datetime.now() - timedelta(days=4))
        self.addon.update(status=amo.STATUS_LITE)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.version-status-actions .warning').text(),
            'Full nomination will be available in 6 days')

    def test_add_version_modal(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        # Make sure checkboxes are visible:
        eq_(doc('.desktop-platforms input.platform').length, 4)
        eq_(doc('.mobile-platforms input.platform').length, 3)
        eq_(set([i.attrib['type'] for i in doc('input.platform')]),
            set(['checkbox']))


class TestVersionEdit(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/thunderbird', 'base/platforms']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = self.get_addon()
        self.version = self.get_version()
        self.url = reverse('devhub.versions.edit',
                           args=['a3615', self.version.id])
        self.v1 = AppVersion(application_id=amo.FIREFOX.id, version='1.0')
        self.v4 = AppVersion(application_id=amo.FIREFOX.id, version='4.0')
        for v in self.v1, self.v4:
            v.save()

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def get_version(self):
        return self.get_addon().current_version

    def formset(self, *args, **kw):
        defaults = {'approvalnotes': 'xxx'}
        defaults.update(kw)
        return formset(*args, **defaults)


class TestVersionEditMobile(TestVersionEdit):

    def setUp(self):
        super(TestVersionEditMobile, self).setUp()
        self.version.apps.all().delete()
        mobile = Application.objects.get(id=amo.MOBILE.id)
        app_vr = AppVersion.objects.create(application=mobile, version='1.0')
        ApplicationsVersions.objects.create(version=self.version,
                                            application=mobile,
                                            min=app_vr, max=app_vr)
        self.version.files.update(platform=amo.PLATFORM_ANDROID.id)

    def test_mobile_platform_options(self):
        ctx = self.client.get(self.url).context
        fld = ctx['file_form'].forms[0]['platform'].field
        # TODO(Kumar) allow PLATFORM_ALL_MOBILE here when it is supported.
        # See bug 646268.
        eq_(sorted(amo.PLATFORMS[p[0]].shortname for p in fld.choices),
            ['android', 'maemo'])


class TestVersionEditDetails(TestVersionEdit):

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
        eq_(r.status_code, 302)
        version = self.get_version()
        eq_(unicode(version.releasenotes), 'xx')
        eq_(unicode(version.approvalnotes), 'yy')

    def test_version_number_redirect(self):
        url = self.url.replace(str(self.version.id), self.version.version)
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, self.url)

    def test_supported_platforms(self):
        res = self.client.get(self.url)
        choices = res.context['new_file_form'].fields['platform'].choices
        taken = [f.platform_id for f in self.version.files.all()]
        platforms = set(self.version.compatible_platforms()) - set(taken)
        eq_(len(choices), len(platforms))

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
        Application(id=52).save()
        for id in [18, 52, 59, 60, 61]:
            av = AppVersion(application_id=id, version='1')
            av.save()
            ApplicationsVersions(application_id=id, min=av, max=av,
                                 version=self.version).save()

        res = self.client.get(self.url)
        doc = pq(res.content)
        assert not res.context['compat_form'].extra_forms
        assert doc('p.add-app')[0].attrib['class'] == 'add-app hide'


class TestVersionEditSearchEngine(TestVersionEdit):
    # https://bugzilla.mozilla.org/show_bug.cgi?id=605941
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json',
                'base/platforms']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])

    def test_search_engine_edit(self):
        dd = self.formset(prefix="files", releasenotes='xx',
                          approvalnotes='yy')

        r = self.client.post(self.url, dd)
        eq_(r.status_code, 302)
        version = Addon.objects.no_cache().get(id=4594).current_version
        eq_(unicode(version.releasenotes), 'xx')
        eq_(unicode(version.approvalnotes), 'yy')

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


class TestVersionEditFiles(TestVersionEdit):

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

        eq_(self.version.files.count(), 1)
        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[0]['DELETE'] = True
        eq_(ActivityLog.objects.count(), 0)
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))

        eq_(ActivityLog.objects.count(), 3)
        log = ActivityLog.objects.order_by('created')[2]
        eq_(log.to_string(), u'File delicious_bookmarks-2.1.072-fx.xpi deleted'
                              ' from <a href="/en-US/firefox/addon/a3615'
                              '/versions/2.1.072">Version 2.1.072</a> of <a '
                              'href="/en-US/firefox/addon/a3615/">Delicious '
                              'Bookmarks</a>.')
        eq_(r.status_code, 302)
        eq_(self.version.files.count(), 0)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_unique_platforms(self):
        # Move the existing file to Linux.
        f = self.version.files.get()
        f.update(platform=Platform.objects.get(id=amo.PLATFORM_LINUX.id))
        # And make a new file for Mac.
        File.objects.create(version=self.version,
                            platform_id=amo.PLATFORM_MAC.id)

        forms = map(initial,
                    self.client.get(self.url).context['file_form'].forms)
        forms[1]['platform'] = forms[0]['platform']
        r = self.client.post(self.url, self.formset(*forms, prefix='files'))
        doc = pq(r.content)
        assert doc('#id_files-0-platform')
        eq_(r.status_code, 200)
        eq_(r.context['file_form'].non_form_errors(),
            ['A platform can only be chosen once.'])

    def test_all_platforms(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        File.objects.create(version=self.version,
                            platform_id=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        res = self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(res.context['file_form'].non_form_errors()[0],
            'The platform All cannot be combined with specific platforms.')

    def test_all_platforms_and_delete(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        File.objects.create(version=self.version,
                    platform_id=amo.PLATFORM_MAC.id)
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # A test that we don't check the platform for deleted files.
        forms[1]['DELETE'] = 1
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(self.version.files.count(), 1)

    def add_in_bsd(self):
        f = self.version.files.get()
        # The default file is All, which prevents the addition of more files.
        f.update(platform=Platform.objects.get(id=amo.PLATFORM_MAC.id))
        return File.objects.create(version=self.version,
                                   platform_id=amo.PLATFORM_BSD.id)

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
        eq_(File.objects.no_cache().get(pk=bsd.pk).platform_id,
            amo.PLATFORM_BSD.id)

    def test_all_unsupported_platforms_change(self):
        bsd = self.add_in_bsd()
        forms = self.client.get(self.url).context['file_form'].forms
        forms = map(initial, forms)
        # Update the file platform to Linux:
        forms[1]['platform'] = amo.PLATFORM_LINUX.id
        self.client.post(self.url, self.formset(*forms, prefix='files'))
        eq_(File.objects.no_cache().get(pk=bsd.pk).platform_id,
            amo.PLATFORM_LINUX.id)
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[1])
        assert 'bsd' not in choices, (
            'After changing BSD file to Linux, BSD should no longer be a '
            'platform choice in: %r' % choices)

    def test_add_file_modal(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        # Make sure radio buttons are visible:
        eq_(doc('.platform ul label').text(), 'Linux Mac OS X Windows')
        eq_(set([i.attrib['type'] for i in doc('input.platform')]),
            set(['radio']))

    def test_mobile_addon_supports_only_mobile_platforms(self):
        app = Application.objects.get(pk=amo.MOBILE.id)
        for a in self.version.apps.all():
            a.application = app
            a.save()
        self.version.files.all().update(platform=amo.PLATFORM_ALL_MOBILE.id)
        forms = self.client.get(self.url).context['file_form'].forms
        choices = self.get_platforms(forms[0])
        eq_(sorted(choices),
            sorted([p.shortname for p in amo.MOBILE_PLATFORMS.values()]))


class TestPlatformSearch(TestVersionEdit):
    fixtures = ['base/apps', 'base/users',
                'base/thunderbird', 'base/addon_4594_a9.json']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.versions.edit',
                           args=['a4594', 42352])
        self.version = Version.objects.get(id=42352)
        self.file = self.version.files.all()[0]
        for platform in amo.PLATFORMS:
            k, _ = Platform.objects.get_or_create(id=platform)

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
        eq_(response.status_code, 302)
        version = Version.objects.no_cache().get(id=42352).files.all()[0]
        eq_(amo.PLATFORM_ALL.id, version.platform.id)


class TestVersionEditCompat(TestVersionEdit):

    def get_form(self, url=None):
        if not url:
            url = self.url
        av = self.version.apps.get()
        eq_(av.min.version, '2.0')
        eq_(av.max.version, '4.0')
        f = self.client.get(url).context['compat_form'].initial_forms[0]
        return initial(f)

    def formset(self, *args, **kw):
        defaults = formset(prefix='files')
        defaults.update(kw)
        return super(TestVersionEditCompat, self).formset(*args, **defaults)

    def test_add_appversion(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = self.formset(initial(f), dict(application=18, min=28, max=29),
                         initial_count=1)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        apps = self.get_version().compatible_apps.keys()
        eq_(sorted(apps), sorted([amo.FIREFOX, amo.THUNDERBIRD]))
        eq_(list(ActivityLog.objects.all().values_list('action')),
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_update_appversion(self):
        d = self.get_form()
        d.update(min=self.v1.id, max=self.v4.id)
        r = self.client.post(self.url,
                             self.formset(d, initial_count=1))
        eq_(r.status_code, 302)
        av = self.version.apps.get()
        eq_(av.min.version, '1.0')
        eq_(av.max.version, '4.0')
        eq_(list(ActivityLog.objects.all().values_list('action')),
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_ajax_update_appversion(self):
        url = reverse('devhub.ajax.compat.update',
                      args=['a3615', self.version.id])
        d = self.get_form(url)
        d.update(min=self.v1.id, max=self.v4.id)
        r = self.client.post(url, self.formset(d, initial_count=1))
        eq_(r.status_code, 200)
        av = self.version.apps.get()
        eq_(av.min.version, '1.0')
        eq_(av.max.version, '4.0')
        eq_(list(ActivityLog.objects.all().values_list('action')),
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_delete_appversion(self):
        # Add thunderbird compat so we can delete firefox.
        self.test_add_appversion()
        f = self.client.get(self.url).context['compat_form']
        d = map(initial, f.initial_forms)
        d[0]['DELETE'] = True
        r = self.client.post(self.url, self.formset(*d, initial_count=2))
        eq_(r.status_code, 302)
        apps = self.get_version().compatible_apps.keys()
        eq_(apps, [amo.THUNDERBIRD])
        eq_(list(ActivityLog.objects.all().values_list('action')),
            [(amo.LOG.MAX_APPVERSION_UPDATED.id,)])

    def test_unique_apps(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        dupe = initial(f)
        del dupe['id']
        d = self.formset(initial(f), dupe, initial_count=1)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        # Because of how formsets work, the second form is expected to be a
        # tbird version range.  We got an error, so we're good.

    def test_require_appversion(self):
        old_av = self.version.apps.get()
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['DELETE'] = True
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 200)
        eq_(r.context['compat_form'].non_form_errors(),
            ['Need at least one compatible application.'])
        eq_(self.version.apps.get(), old_av)

    def test_proper_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'], d['max'] = d['max'], d['min']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 200)
        eq_(r.context['compat_form'].forms[0].non_field_errors(),
            ['Invalid version range.'])

    def test_same_min_max(self):
        f = self.client.get(self.url).context['compat_form'].initial_forms[0]
        d = initial(f)
        d['min'] = d['max']
        r = self.client.post(self.url, self.formset(d, initial_count=1))
        eq_(r.status_code, 302)
        av = self.version.apps.all()[0]
        eq_(av.min, av.max)
