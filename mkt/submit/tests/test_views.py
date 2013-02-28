# -*- coding: utf-8 -*-
import datetime
import json
import os
import shutil
import zipfile

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.signals import request_finished

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import es.hold

import amo
import amo.tests
from amo.tests import formset, initial
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.models import (Addon, AddonCategory, AddonDeviceType, AddonUser,
                           Category)
from apps.users.models import UserNotification
from apps.users.notifications import app_surveys
from constants.applications import DEVICE_TYPES
from files.tests.test_models import UploadTest as BaseUploadTest
from translations.models import Translation
from users.models import UserProfile

import mkt
from mkt.site.fixtures import fixture
from mkt.submit.forms import NewWebappVersionForm
from mkt.submit.models import AppSubmissionChecklist
from mkt.submit.decorators import read_dev_agreement_required
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


class TestSubmit(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        request_finished.disconnect(es.hold.process,
                                    dispatch_uid='process_es_tasks_on_finish')
        self.gia_mock = mock.patch(
            'mkt.developers.tasks.generate_image_assets').__enter__()
        self.fi_mock = mock.patch(
            'mkt.developers.tasks.fetch_icon').__enter__()
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='password')

    def tearDown(self):
        self.gia_mock.__exit__()
        self.fi_mock.__exit__()

    def get_user(self):
        return UserProfile.objects.get(username='regularuser')

    def get_url(self, url):
        return reverse('submit.app.%s' % url, args=[self.webapp.app_slug])

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

        # Check that we link back to the Developer Agreement.
        terms_link = progress.find('.terms a')
        if 'terms' in completed:
            eq_(terms_link.attr('href'),
                reverse('mkt.developers.docs', args=['policies', 'agreement']))
        else:
            eq_(terms_link.length, 0)

        # Check the current step.
        eq_(progress.find('.current').text(),
            unicode(mkt.APP_STEPS_TITLE[current]))


class TestProceed(TestSubmit):

    def setUp(self):
        super(TestProceed, self).setUp()
        self.user.update(read_dev_agreement=None)
        self.url = reverse('submit.app')

    def test_is_authenticated(self):
        # Redirect user to Terms.
        r = self.client.get(self.url)
        self.assert3xx(r, reverse('submit.app.terms'))

    def test_is_anonymous(self):
        # Show user to Terms page but with the login prompt.
        self.client.logout()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(r.context['proceed'], True)


class TestTerms(TestSubmit):

    def setUp(self):
        super(TestTerms, self).setUp()
        self.user.update(read_dev_agreement=None)
        self.url = reverse('submit.app.terms')

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def test_jump_to_step(self):
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assert3xx(r, self.url)

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('#submit-terms')
        eq_(doc.length, 1)
        eq_(doc.find('input[name=newsletter]').siblings('label').length, 1,
            'Missing its <label>!')

    def test_progress_display(self):
        self._test_progress_display([], 'terms')

    def test_agree(self):
        self.client.post(self.url, {'read_dev_agreement': True})
        dt = self.get_user().read_dev_agreement
        self.assertCloseToNow(dt)
        eq_(UserNotification.objects.count(), 0)

    def test_agree_and_sign_me_up(self):
        self.client.post(self.url, {'read_dev_agreement':
                                    datetime.datetime.now(),
                                    'newsletter': True})
        dt = self.get_user().read_dev_agreement
        self.assertCloseToNow(dt)
        eq_(UserNotification.objects.count(), 1)
        notes = UserNotification.objects.filter(user=self.user, enabled=True,
                                                notification_id=app_surveys.id)
        eq_(notes.count(), 1, 'Expected to not be subscribed to newsletter')

    def test_disagree(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 200)
        eq_(self.user.read_dev_agreement, None)
        eq_(UserNotification.objects.count(), 0)

    def test_read_dev_agreement_required(self):
        f = mock.Mock()
        f.__name__ = 'function'
        request = mock.Mock()
        request.amo_user.read_dev_agreement = None
        request.get_full_path.return_value = self.url
        func = read_dev_agreement_required(f)
        res = func(request)
        assert not f.called
        eq_(res.status_code, 302)
        eq_(res['Location'], reverse('submit.app'))


class TestManifest(TestSubmit):

    def setUp(self):
        super(TestManifest, self).setUp()
        self.user.update(read_dev_agreement=None)
        self.url = reverse('submit.app')

    def _step(self):
        self.user.update(read_dev_agreement=datetime.datetime.now())

    def test_anonymous(self):
        r = self.client.get(self.url, follow=True)
        eq_(r.context['step'], 'terms')

    def test_cannot_skip_prior_step(self):
        r = self.client.get(self.url, follow=True)
        # And we start back at one...
        self.assert3xx(r, reverse('submit.app.terms'))

    def test_jump_to_step(self):
        # I already read the Terms.
        self._step()
        # So jump me to the Manifest step.
        r = self.client.get(reverse('submit.app'), follow=True)
        eq_(r.context['step'], 'manifest')

    def test_legacy_redirects(self):
        def check():
            for before, status in redirects:
                r = self.client.get(before, follow=True)
                self.assert3xx(r, dest, status)

        # I haven't read the dev agreement.
        redirects = (
            ('/developers/submit/', 302),
            ('/developers/submit/app', 302),
            ('/developers/submit/app/terms', 302),
            ('/developers/submit/app/manifest', 302),
        )
        dest = '/developers/submit/terms'
        check()

        # I have read the dev agreement.
        self._step()
        redirects = (
            ('/developers/submit/app', 302),
            ('/developers/submit/app/terms', 302),
            ('/developers/submit/app/manifest', 302),
            ('/developers/submit/manifest', 301),
        )
        dest = '/developers/submit/'
        check()

    def test_page(self):
        self._step()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#upload-file').length, 1)

    def test_progress_display(self):
        self._step()
        self._test_progress_display(['terms'], 'manifest')


class UploadAddon(object):

    def post(self, expect_errors=False, data=None):
        if data is None:
            data = {'free_platforms': ['free-desktop']}
        data.update(upload=self.upload.pk)
        r = self.client.post(self.url, data, follow=True)
        eq_(r.status_code, 200)
        if not expect_errors:
            # Show any unexpected form errors.
            if r.context and 'form' in r.context:
                eq_(r.context['form'].errors, {})
        return r


class BaseWebAppTest(BaseUploadTest, UploadAddon, amo.tests.TestCase):
    fixtures = fixture('app_firefox', 'platform_all', 'user_999', 'user_10482')

    def setUp(self):
        super(BaseWebAppTest, self).setUp()
        self.manifest = self.manifest_path('mozball.webapp')
        self.manifest_url = 'http://allizom.org/mozball.webapp'
        self.upload = self.get_upload(abspath=self.manifest)
        self.upload.update(name=self.manifest_url, is_webapp=True)
        self.url = reverse('submit.app')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def post_addon(self, data=None):
        eq_(Addon.objects.count(), 0)
        self.post(data=data)
        return Addon.objects.get()


class TestCreateWebApp(BaseWebAppTest):

    def test_post_app_redirect(self):
        r = self.post()
        webapp = Webapp.objects.get()
        self.assert3xx(r,
            reverse('submit.app.details', args=[webapp.app_slug]))

    def test_no_hint(self):
        self.post_addon()
        self.upload = self.get_upload(abspath=self.manifest)
        r = self.client.post(reverse('mkt.developers.upload_manifest'),
                             dict(manifest=self.manifest_url), follow=True)
        eq_(r.status_code, 200)
        assert 'already submitted' not in r.content, (
            'Unexpected helpful error (trap_duplicate)')
        assert 'already exists' not in r.content, (
            'Unexpected validation error (verify_app_domain)')

    def test_no_upload(self):
        data = {'free_platforms': ['free-desktop']}
        res = self.client.post(self.url, data, follow=True)
        eq_(res.context['form'].errors,
            {'upload': NewWebappVersionForm.upload_error})

    def test_bad_upload(self):
        data = {'free_platforms': ['free-desktop'], 'upload': 'foo'}
        res = self.client.post(self.url, data, follow=True)
        eq_(res.context['form'].errors,
            {'upload': NewWebappVersionForm.upload_error})

    def test_hint_for_same_manifest(self):
        self.create_switch(name='webapps-unique-by-domain')
        self.post_addon()
        self.upload = self.get_upload(abspath=self.manifest)
        r = self.client.post(reverse('mkt.developers.upload_manifest'),
                             dict(manifest=self.manifest_url))
        data = json.loads(r.content)
        assert 'Oops' in data['validation']['messages'][0]['message'], (
            'Expected oops')

    def test_no_hint_for_same_manifest_different_author(self):
        self.create_switch(name='webapps-unique-by-domain')
        self.post_addon()

        # Submit same manifest as different user.
        assert self.client.login(username='clouserw@gmail.com',
                                 password='password')
        self.upload = self.get_upload(abspath=self.manifest)
        r = self.client.post(reverse('mkt.developers.upload_manifest'),
                             dict(manifest=self.manifest_url))

        data = json.loads(r.content)
        eq_(data['validation']['messages'][0]['message'],
            'An app already exists on this domain; only one app per domain is '
            'allowed.')

    def test_app_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.type, amo.ADDON_WEBAPP)
        eq_(addon.is_packaged, False)
        assert addon.guid is not None, (
            'Expected app to have a UUID assigned to guid')
        eq_(unicode(addon.name), u'MozillaBall ょ')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, u'mozillaball-ょ')
        eq_(addon.summary, u'Exciting Open Web development action!')
        eq_(addon.manifest_url, u'http://allizom.org/mozball.webapp')
        eq_(addon.app_domain, u'http://allizom.org')
        eq_(Translation.objects.get(id=addon.summary.id, locale='it'),
            u'Azione aperta emozionante di sviluppo di fotoricettore!')

    def test_manifest_with_any_extension(self):
        self.manifest = os.path.join(settings.ROOT, 'mkt', 'developers',
                                     'tests', 'addons', 'mozball.owa')
        self.upload = self.get_upload(abspath=self.manifest, is_webapp=True)
        addon = self.post_addon()
        eq_(addon.type, amo.ADDON_WEBAPP)

    def test_version_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.current_version.version, '1.0')

    def test_file_from_uploaded_manifest(self):
        addon = self.post_addon()
        files = addon.current_version.files.all()
        eq_(len(files), 1)
        eq_(files[0].status, amo.STATUS_PENDING)

    def test_set_platform(self):
        app = self.post_addon(
            {'free_platforms': ['free-android-tablet', 'free-desktop']})
        self.assertSetEqual(app.device_types,
                            [amo.DEVICE_TABLET, amo.DEVICE_DESKTOP])

    def test_free(self):
        app = self.post_addon({'free_platforms': ['free-firefoxos']})
        self.assertSetEqual(app.device_types, [amo.DEVICE_GAIA])
        eq_(app.premium_type, amo.ADDON_FREE)

    def test_premium(self):
        self.create_switch('allow-b2g-paid-submission')
        app = self.post_addon({'paid_platforms': ['paid-firefoxos']})
        self.assertSetEqual(app.device_types, [amo.DEVICE_GAIA])
        eq_(app.premium_type, amo.ADDON_PREMIUM)

    def test_short_locale(self):
        # This manifest has a locale code of "pt" which is in the
        # SHORTER_LANGUAGES setting and should get converted to "pt-PT".
        self.manifest = self.manifest_path('short-locale.webapp')
        self.upload = self.get_upload(abspath=self.manifest)
        addon = self.post_addon()
        eq_(addon.default_locale, 'pt-PT')

    def test_unsupported_detail_locale(self):
        # This manifest has a locale code of "en-GB" which is unsupported, so
        # we default to "en-US".
        self.manifest = self.manifest_path('unsupported-default-locale.webapp')
        self.upload = self.get_upload(abspath=self.manifest)
        addon = self.post_addon()
        eq_(addon.default_locale, 'en-US')


class TestCreateWebAppFromManifest(BaseWebAppTest):

    def setUp(self):
        super(TestCreateWebAppFromManifest, self).setUp()
        Webapp.objects.create(app_slug='xxx',
                              app_domain='http://existing-app.com')

    def upload_webapp(self, manifest_url, **post_kw):
        self.upload.update(name=manifest_url)  # Simulate JS upload.
        return self.post(**post_kw)

    def post_manifest(self, manifest_url):
        rs = self.client.post(reverse('mkt.developers.upload_manifest'),
                              dict(manifest=manifest_url))
        if 'json' in rs['content-type']:
            rs = json.loads(rs.content)
        return rs

    def test_duplicate_domain(self):
        self.create_switch(name='webapps-unique-by-domain')
        rs = self.upload_webapp('http://existing-app.com/my.webapp',
                                expect_errors=True)
        eq_(rs.context['form'].errors,
            {'upload':
             ['An app already exists on this domain; only one '
              'app per domain is allowed.']})

    def test_allow_duplicate_domains(self):
        self.upload_webapp('http://existing-app.com/my.webapp')  # No errors.

    def test_duplicate_domain_from_js(self):
        self.create_switch(name='webapps-unique-by-domain')
        data = self.post_manifest('http://existing-app.com/my.webapp')
        eq_(data['validation']['errors'], 1)
        eq_(data['validation']['messages'][0]['message'],
            'An app already exists on this domain; '
            'only one app per domain is allowed.')

    def test_allow_duplicate_domains_from_js(self):
        rs = self.post_manifest('http://existing-app.com/my.webapp')
        eq_(rs.status_code, 302)


class BasePackagedAppTest(BaseUploadTest, UploadAddon, amo.tests.TestCase):
    fixtures = fixture('webapp_337141', 'user_999')

    def setUp(self):
        request_finished.disconnect(es.hold.process,
                                    dispatch_uid='process_es_tasks_on_finish')
        super(BasePackagedAppTest, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        self.version = self.app.current_version
        self.file = self.version.all_files[0]
        self.file.update(filename='mozball.zip')

        self.package = self.packaged_app_path('mozball.zip')
        self.upload = self.get_upload(abspath=self.package)
        self.upload.update(name='mozball.zip', is_webapp=True)
        self.url = reverse('submit.app')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def post_addon(self, data=None):
        eq_(Addon.objects.count(), 1)
        self.post(data=data)
        return Addon.objects.order_by('-id')[0]

    def setup_files(self, filename='mozball.zip'):
        # Make sure the source file is there.
        # Original packaged file.
        if not storage.exists(self.file.file_path):
            try:
                # We don't care if these dirs exist.
                os.makedirs(os.path.dirname(self.file.file_path))
            except OSError:
                pass
            shutil.copyfile(self.packaged_app_path(filename),
                            self.file.file_path)
        # Signed packaged file.
        if not storage.exists(self.file.signed_file_path):
            try:
                # We don't care if these dirs exist.
                os.makedirs(os.path.dirname(self.file.signed_file_path))
            except OSError:
                pass
            shutil.copyfile(self.packaged_app_path(filename),
                            self.file.signed_file_path)


class TestCreatePackagedApp(BasePackagedAppTest):

    def test_post_app_redirect(self):
        res = self.post()
        webapp = Webapp.objects.order_by('-created')[0]
        self.assert3xx(res,
            reverse('submit.app.details', args=[webapp.app_slug]))

    def test_app_from_uploaded_package(self):
        addon = self.post_addon(
            data={'packaged': True, 'free_platforms': ['free-firefoxos']})
        eq_(addon.type, amo.ADDON_WEBAPP)
        eq_(addon.current_version.version, '1.0')
        eq_(addon.is_packaged, True)
        assert addon.guid is not None, (
            'Expected app to have a UUID assigned to guid')
        eq_(unicode(addon.name), u'Packaged MozillaBall ょ')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, u'packaged-mozillaball-ょ')
        eq_(addon.summary, u'Exciting Open Web development action!')
        eq_(addon.manifest_url, None)
        eq_(addon.app_domain, None)
        eq_(Translation.objects.get(id=addon.summary.id, locale='it'),
            u'Azione aperta emozionante di sviluppo di fotoricettore!')

    @mock.patch('mkt.developers.forms.verify_app_domain')
    def test_packaged_app_not_unique_by_domain(self, _verify):
        self.post(
            data={'packaged': True, 'free_platforms': ['free-firefoxos']})
        assert not _verify.called, (
            '`verify_app_domain` should not be called for packaged apps.')

    def test_packaged_app_has_ids_file(self):
        app = self.post_addon(
            data={'packaged': True, 'free_platforms': ['free-firefoxos']})
        file_ = app.versions.latest().files.latest()
        filename = 'META-INF/ids.json'
        zf = zipfile.ZipFile(file_.file_path)
        assert zf.getinfo(filename), (
            'Expected %s in zip archive but not found.' % filename)
        ids = json.loads(zf.read(filename))
        eq_(ids['app_id'], app.guid)
        eq_(ids['version_id'], file_.version_id)


class TestDetails(TestSubmit):
    fixtures = fixture('webapp_337141', 'user_999', 'user_10482')

    def setUp(self):
        self.gia_mock = mock.patch(
            'mkt.developers.tasks.generate_image_assets').__enter__()
        self.fi_mock = mock.patch(
            'mkt.developers.tasks.fetch_icon').__enter__()
        super(TestDetails, self).setUp()
        self.webapp = self.get_webapp()
        self.webapp.update(status=amo.STATUS_NULL)
        self.url = reverse('submit.app.details', args=[self.webapp.app_slug])

    def tearDown(self):
        self.gia_mock.__exit__()
        self.fi_mock.__exit__()

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def upload_preview(self, image_file=None):
        if not image_file:
            image_file = get_image_path('preview.jpg')
        return self._upload_image(self.webapp.get_dev_url('upload_preview'),
                                  image_file=image_file)

    def upload_icon(self, image_file=None):
        if not image_file:
            image_file = get_image_path('mozilla-sq.png')
        return self._upload_image(self.webapp.get_dev_url('upload_icon'),
                                  image_file=image_file)

    def _upload_image(self, url, image_file):
        with open(image_file, 'rb') as data:
            rp = self.client.post(url, {'upload_image': data})
        eq_(rp.status_code, 200)
        hash_ = json.loads(rp.content)['upload_hash']
        assert hash_, 'No hash: %s' % rp.content
        return hash_

    def _step(self):
        self.user.update(read_dev_agreement=datetime.datetime.now())
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp,
            terms=True, manifest=True)

        # Associate app with user.
        AddonUser.objects.create(addon=self.webapp, user=self.user)

        # Associate device type with app.
        self.dtype = DEVICE_TYPES.values()[0]
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=self.dtype.id)
        self.device_types = [self.dtype]

        # Associate category with app.
        self.cat1 = Category.objects.create(type=amo.ADDON_WEBAPP, name='Fun')
        AddonCategory.objects.create(addon=self.webapp, category=self.cat1)

    def test_anonymous(self):
        self._test_anonymous()

    def test_resume_later(self):
        self._step()
        self.webapp.appsubmissionchecklist.update(details=True)
        r = self.client.get(reverse('submit.app.resume',
                                    args=[self.webapp.app_slug]))
        self.assert3xx(r, self.webapp.get_dev_url('edit'))

    def test_not_owner(self):
        self._step()
        assert self.client.login(username='clouserw@gmail.com',
                                 password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_page(self):
        self._step()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#submit-details').length, 1)

    def test_progress_display(self):
        self._step()
        self._test_progress_display(['terms', 'manifest'], 'details')

    def new_preview_formset(self, *args, **kw):
        ctx = self.client.get(self.url).context

        blank = initial(ctx['form_previews'].forms[-1])
        blank.update(**kw)
        return blank

    def preview_formset(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.new_preview_formset()], **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def get_dict(self, **kw):
        data = {
            'app_slug': 'testname',
            'summary': 'Hello!',
            'description': 'desc',
            'privacy_policy': 'XXX <script>alert("xss")</script>',
            'homepage': 'http://www.goodreads.com/user/show/7595895-krupa',
            'support_url': 'http://www.goodreads.com/user_challenges/351558',
            'support_email': 'krupa+to+the+rescue@goodreads.com',
            'categories': [self.cat1.id],
            'flash': '1',
            'publish': '1'
        }
        # Add the required screenshot.
        data.update(self.preview_formset({
            'upload_hash': '<hash>',
            'position': 0
        }))
        data.update(**kw)
        # Remove fields without values.
        data = dict((k, v) for k, v in data.iteritems() if v is not None)
        return data

    def check_dict(self, data=None, expected=None):
        if data is None:
            data = self.get_dict()
        addon = self.get_webapp()

        # Build a dictionary of expected results.
        expected_data = {
            'app_slug': 'testname',
            'summary': 'Hello!',
            'description': 'desc',
            'privacy_policy': 'XXX &lt;script&gt;alert("xss")&lt;/script&gt;',
            'uses_flash': True,
            'make_public': amo.PUBLIC_IMMEDIATELY
        }
        if expected:
            expected_data.update(expected)

        for field, expected in expected_data.iteritems():
            got = unicode(getattr(addon, field))
            expected = unicode(expected)
            eq_(got, expected,
                'Expected %r for %r. Got %r.' % (expected, field, got))

        self.assertSetEqual(addon.device_types, self.device_types)

    def test_success(self):
        self._step()
        data = self.get_dict()
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)
        self.check_dict(data=data)
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('done'))

        eq_(self.webapp.status, amo.STATUS_PENDING)

    def test_success_paid(self):
        self._step()

        self.webapp = self.get_webapp()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)

        data = self.get_dict()
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)
        self.check_dict(data=data)
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('done'))

        eq_(self.webapp.status, amo.STATUS_NULL)
        eq_(self.webapp.highest_status, amo.STATUS_PENDING)
        self.assertSetEqual(
            self.webapp.get_region_ids(), mkt.regions.ALL_PAID_REGION_IDS)

    def test_success_prefill_device_types_if_empty(self):
        """
        The new submission flow asks for device types at step one.
        This ensures that existing incomplete apps still have device
        compatibility.
        """
        self._step()

        AddonDeviceType.objects.all().delete()
        self.device_types = amo.DEVICE_TYPES.values()

        data = self.get_dict()
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)
        self.check_dict(data=data)
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('done'))

    def test_success_for_public_waiting(self):
        self._step()

        data = self.get_dict()
        del data['publish']

        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)

        self.check_dict(data=data, expected={'make_public': amo.PUBLIC_WAIT})
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('done'))

    def test_media_types(self):
        self._step()
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('.screenshot_upload').attr('data-allowed-types'),
            'image/jpeg|image/png|video/webm')
        eq_(doc('#id_icon_upload').attr('data-allowed-types'),
            'image/jpeg|image/png')

    def test_screenshot(self):
        self._step()
        im_hash = self.upload_preview()
        data = self.get_dict()
        data.update(self.preview_formset({
            'upload_hash': im_hash,
            'position': 0
        }))
        rp = self.client.post(self.url, data)
        eq_(rp.status_code, 302)
        ad = Addon.objects.get(pk=self.webapp.pk)
        eq_(ad.previews.all().count(), 1)

    def test_icon(self):
        self._step()
        im_hash = self.upload_icon()
        data = self.get_dict()
        data['icon_upload_hash'] = im_hash
        data['icon_type'] = 'image/png'
        rp = self.client.post(self.url, data)
        eq_(rp.status_code, 302)
        ad = self.get_webapp()
        eq_(ad.icon_type, 'image/png')
        for size in amo.ADDON_ICON_SIZES:
            fn = '%s-%s.png' % (ad.id, size)
            assert os.path.exists(os.path.join(ad.get_icon_dir(), fn)), (
                'Expected %s in %s' % (fn, os.listdir(ad.get_icon_dir())))

    def test_screenshot_or_video_required(self):
        self._step()
        data = self.get_dict()
        for k in data:
            if k.startswith('files') and k.endswith('upload_hash'):
                data[k] = ''
        rp = self.client.post(self.url, data)
        eq_(rp.context['form_previews'].non_form_errors(),
            ['You must upload at least one screenshot or video.'])

    def test_unsaved_screenshot(self):
        self._step()
        # If there are form errors we should still pass the previews URIs.
        preview_type = 'video/webm'
        preview_uri = 'moz-filedata:p00p'
        data = self.preview_formset({
            'position': 1,
            'upload_hash': '<hash_one>',
            'unsaved_image_type': preview_type,
            'unsaved_image_data': preview_uri
        })
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        form = pq(r.content)('form')
        eq_(form.find('input[name=files-0-unsaved_image_type]').val(),
            preview_type)
        eq_(form.find('input[name=files-0-unsaved_image_data]').val(),
            preview_uri)

    def test_unique_allowed(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(name=self.webapp.name))
        self.assertNoFormErrors(r)
        app = Webapp.objects.exclude(app_slug=self.webapp.app_slug)[0]
        self.assert3xx(r, reverse('submit.app.done', args=[app.app_slug]))
        eq_(self.get_webapp().status, amo.STATUS_PENDING)

    def test_slug_invalid(self):
        self._step()
        # Submit an invalid slug.
        d = self.get_dict(app_slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'app_slug',
            "Enter a valid 'slug' consisting of letters, numbers, underscores "
            "or hyphens.")

    def test_slug_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(app_slug=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'app_slug',
                             'This field is required.')

    def test_summary_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(summary=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'summary',
                             'This field is required.')

    def test_summary_length(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(summary='a' * 1025))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'summary',
            'Ensure this value has at most 1024 characters (it has 1025).')

    def test_description_optional(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(description=None))
        self.assertNoFormErrors(r)

    def test_privacy_policy_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(privacy_policy=None))
        self.assertFormError(r, 'form_basic', 'privacy_policy',
                             'This field is required.')

    def test_clashing_locale(self):
        self.webapp.default_locale = 'de'
        self.webapp.save()
        self._step()
        self.client.cookies['current_locale'] = 'en-us'
        data = self.get_dict(name=None, name_de='Test name',
                             privacy_policy=None,
                             **{'privacy_policy_en-us': 'XXX'})
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)

    def test_homepage_url_optional(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(homepage=None))
        self.assertNoFormErrors(r)

    def test_homepage_url_invalid(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(homepage='xxx'))
        self.assertFormError(r, 'form_basic', 'homepage', 'Enter a valid URL.')

    def test_support_url_optional(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(support_url=None))
        self.assertNoFormErrors(r)

    def test_support_url_invalid(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(support_url='xxx'))
        self.assertFormError(r, 'form_basic', 'support_url',
                             'Enter a valid URL.')

    def test_support_email_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(support_email=None))
        self.assertFormError(r, 'form_basic', 'support_email',
                             'This field is required.')

    def test_support_email_invalid(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(support_email='xxx'))
        self.assertFormError(r, 'form_basic', 'support_email',
                             'Enter a valid e-mail address.')

    def test_categories_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(categories=[]))
        eq_(r.context['form_cats'].errors['categories'],
            ['This field is required.'])

    def test_categories_max(self):
        self._step()
        eq_(amo.MAX_CATEGORIES, 2)
        cat2 = Category.objects.create(type=amo.ADDON_WEBAPP, name='bling')
        cat3 = Category.objects.create(type=amo.ADDON_WEBAPP, name='blang')
        cats = [self.cat1.id, cat2.id, cat3.id]
        r = self.client.post(self.url, self.get_dict(categories=cats))
        eq_(r.context['form_cats'].errors['categories'],
            ['You can have only 2 categories.'])

    def _post_cats(self, cats):
        self.client.post(self.url, self.get_dict(categories=cats))
        eq_(sorted(self.get_webapp().categories.values_list('id', flat=True)),
            sorted(cats))

    def test_categories_add(self):
        self._step()
        cat2 = Category.objects.create(type=amo.ADDON_WEBAPP, name='bling')
        self._post_cats([self.cat1.id, cat2.id])

    def test_categories_add_and_remove(self):
        self._step()
        cat2 = Category.objects.create(type=amo.ADDON_WEBAPP, name='bling')
        self._post_cats([cat2.id])

    def test_categories_remove(self):
        # Add another category here so it gets added to the initial formset.
        cat2 = Category.objects.create(type=amo.ADDON_WEBAPP, name='bling')
        AddonCategory.objects.create(addon=self.webapp, category=cat2)
        self._step()

        # `cat2` should get removed.
        self._post_cats([self.cat1.id])

    def test_games_default_excluded_in_brazil(self):
        games = Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        self._step()

        r = self.client.post(self.url, self.get_dict(categories=[games.id]))
        self.assertNoFormErrors(r)
        eq_(list(AER.objects.values_list('region', flat=True)),
            [mkt.regions.BR.id])

    def test_other_categories_are_not_excluded(self):
        # Keep the category around for good measure.
        Category.objects.create(type=amo.ADDON_WEBAPP, slug='games')
        self._step()

        r = self.client.post(self.url, self.get_dict())
        self.assertNoFormErrors(r)
        eq_(AER.objects.count(), 0)


class TestDone(TestSubmit):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestDone, self).setUp()
        self.webapp = self.get_webapp()
        self.url = reverse('submit.app.done', args=[self.webapp.app_slug])

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def _step(self, **kw):
        data = dict(addon=self.webapp, terms=True, manifest=True,
                    details=True)
        data.update(kw)
        self.cl = AppSubmissionChecklist.objects.create(**data)
        AddonUser.objects.create(addon=self.webapp, user=self.user)

    def test_anonymous(self):
        self._test_anonymous()

    def test_progress_display(self):
        self._step()
        self._test_progress_display(['terms', 'manifest', 'details'], 'done')

    def test_done(self):
        self._step()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
