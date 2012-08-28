# -*- coding: utf-8 -*-
import datetime
import json
import os

from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
import paypal
from amo.helpers import urlparams
from amo.tests import close_to_now, formset, initial
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.models import (Addon, AddonCategory, AddonDeviceType, AddonUser,
                           Category)
from addons.utils import ReverseNameLookup
from apps.users.models import UserNotification
from apps.users.notifications import app_surveys
from constants.applications import DEVICE_TYPES
from files.tests.test_models import UploadTest as BaseUploadTest
from market.models import Price
from translations.models import Translation
from users.models import UserProfile

import mkt
from mkt.submit.models import AppSubmissionChecklist
from mkt.submit.decorators import read_dev_agreement_required
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


class TestSubmit(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='password')

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


class TestTerms(TestSubmit):
    fixtures = ['base/users']

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
        self.create_switch(name='allow-packaged-app-uploads')
        r = self.client.post(self.url, {'read_dev_agreement': True})
        self.assert3xx(r, reverse('submit.app.choose'))
        dt = self.get_user().read_dev_agreement
        assert close_to_now(dt), (
            'Expected date of agreement read to be close to now. Was %s' % dt)
        eq_(UserNotification.objects.count(), 0)

    def test_agree_and_sign_me_up(self):
        self.create_switch(name='allow-packaged-app-uploads')
        r = self.client.post(self.url, {'read_dev_agreement':
                                        datetime.datetime.now(),
                                        'newsletter': True})
        self.assert3xx(r, reverse('submit.app.choose'))
        dt = self.get_user().read_dev_agreement
        assert close_to_now(dt), (
            'Expected date of agreement read to be close to now. Was %s' % dt)
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
    fixtures = ['base/users']

    def setUp(self):
        super(TestManifest, self).setUp()
        self.user.update(read_dev_agreement=None)
        self.url = reverse('submit.app.manifest')

    def _step(self):
        self.user.update(read_dev_agreement=datetime.datetime.now())

    def test_anonymous(self):
        self._test_anonymous()

    def test_cannot_skip_prior_step(self):
        r = self.client.get(self.url, follow=True)
        # And we start back at one...
        self.assert3xx(r, reverse('submit.app.terms'))

    def test_jump_to_step(self):
        # I already read the Terms.
        self._step()
        # So jump me to the Manifest step.
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assert3xx(r, reverse('submit.app.manifest'))
        # Now with waffles!
        self.create_switch(name='allow-packaged-app-uploads')
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assert3xx(r, reverse('submit.app.choose'))

    def test_page(self):
        self._step()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#submit-manifest').length, 1)

    def test_progress_display(self):
        self._step()
        self._test_progress_display(['terms'], 'manifest')


class UploadAddon(object):

    def post(self, desktop_platforms=[amo.PLATFORM_ALL], mobile_platforms=[],
             expect_errors=False):
        d = dict(upload=self.upload.pk,
                 desktop_platforms=[p.id for p in desktop_platforms],
                 mobile_platforms=[p.id for p in mobile_platforms])
        r = self.client.post(self.url, d, follow=True)
        eq_(r.status_code, 200)
        if not expect_errors:
            # Show any unexpected form errors.
            if r.context and 'form' in r.context:
                eq_(r.context['form'].errors, {})
        return r


class BaseWebAppTest(BaseUploadTest, UploadAddon, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms']

    def setUp(self):
        super(BaseWebAppTest, self).setUp()
        self.manifest = self.manifest_path('mozball.webapp')
        self.manifest_url = 'http://allizom.org/mozball.webapp'
        self.upload = self.get_upload(abspath=self.manifest)
        self.upload.update(name=self.manifest_url, is_webapp=True)
        self.url = reverse('submit.app.manifest')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        # Complete first step.
        self.client.post(reverse('submit.app.terms'),
                         {'read_dev_agreement': True})

    def post_addon(self):
        eq_(Addon.objects.count(), 0)
        self.post()
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
        eq_(addon.guid, None)
        eq_(unicode(addon.name), u'MozillaBall ょ')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, u'mozillaball-ょ')
        eq_(addon.summary, u'Exciting Open Web development action!')
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
    fixtures = ['base/apps', 'base/users', 'base/platforms']

    def setUp(self):
        super(BasePackagedAppTest, self).setUp()
        self.create_switch(name='allow-packaged-app-uploads')
        self.package = self.packaged_app_path('mozball.zip')
        self.upload = self.get_upload(abspath=self.package)
        self.upload.update(name='mozball.zip', is_webapp=True)
        self.url = reverse('submit.app.package')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        # Complete first step.
        self.client.post(reverse('submit.app.terms'),
                         {'read_dev_agreement': True})

    def post_addon(self):
        eq_(Addon.objects.count(), 0)
        self.post()
        return Addon.objects.get()


class TestCreatePackagedApp(BasePackagedAppTest):

    def test_post_app_redirect(self):
        res = self.post()
        webapp = Webapp.objects.get()
        self.assert3xx(res,
            reverse('submit.app.details', args=[webapp.app_slug]))

    def test_app_from_uploaded_package(self):
        addon = self.post_addon()
        eq_(addon.type, amo.ADDON_WEBAPP)
        eq_(addon.current_version.version, '1.0')
        eq_(addon.is_packaged, True)
        eq_(addon.guid, None)
        eq_(unicode(addon.name), u'Packaged MozillaBall ょ')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, u'packaged-mozillaball-ょ')
        eq_(addon.summary, u'Exciting Open Web development action!')
        eq_(Translation.objects.get(id=addon.summary.id, locale='it'),
            u'Azione aperta emozionante di sviluppo di fotoricettore!')

    @mock.patch('mkt.submit.forms.verify_app_domain')
    def test_packaged_app_not_unique_by_domain(self, _verify):
        self.create_switch(name='webapps-unique-by-domain')
        self.post()
        assert not _verify.called, ('`verify_app_domain` should not be called'
                                    ' for packaged apps.')


class TestDetails(TestSubmit):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestDetails, self).setUp()
        self.webapp = self.get_webapp()
        self.webapp.update(status=amo.STATUS_NULL)
        self.url = reverse('submit.app.details', args=[self.webapp.app_slug])

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def upload_preview(self, image_file=None):
        return self._upload_image(self.webapp.get_dev_url('upload_preview'),
                                  image_file=image_file)

    def upload_icon(self, image_file=None):
        return self._upload_image(self.webapp.get_dev_url('upload_icon'),
                                  image_file=image_file)

    def _upload_image(self, url, image_file=None):
        if not image_file:
            image_file = get_image_path('non-animated.png')
        with open(image_file, 'rb') as data:
            rp = self.client.post(url, {'upload_image': data})
        eq_(rp.status_code, 200)
        return json.loads(rp.content)['upload_hash']

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

        # Associate category with app.
        self.cat1 = Category.objects.create(type=amo.ADDON_WEBAPP, name='Fun')
        AddonCategory.objects.create(addon=self.webapp, category=self.cat1)

    def test_anonymous(self):
        self._test_anonymous()

    def test_resume_step(self):
        self._step()
        payments_url = reverse('submit.app.payments',
                               args=[self.webapp.app_slug])
        r = self.client.get(payments_url, follow=True)
        self.assert3xx(r, reverse('submit.app.details',
                                  args=[self.webapp.app_slug]))

    def test_resume_later(self):
        self._step()
        self.webapp.appsubmissionchecklist.update(details=True, payments=True)
        self.webapp.update(paypal_id='', premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(reverse('submit.app.resume',
                                      args=[self.webapp.app_slug]))
        self.assert3xx(res, self.webapp.get_dev_url('paypal_setup'))

    def test_disabled_payments_resume_later(self):
        self.create_switch(name='disabled-payments')
        self._step()
        r = self.client.get(reverse('submit.app.resume',
                                    args=[self.webapp.app_slug]))
        assert r['Location'].endswith(self.url), 'Expected: %s' % self.url

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
            'name': 'Test name',
            'slug': 'testname',
            'summary': 'Hello!',
            'description': 'desc',
            'privacy_policy': 'XXX <script>alert("xss")</script>',
            'homepage': 'http://www.goodreads.com/user/show/7595895-krupa',
            'support_url': 'http://www.goodreads.com/user_challenges/351558',
            'support_email': 'krupa+to+the+rescue@goodreads.com',
            'device_types': [self.dtype.id],
            'categories': [self.cat1.id],
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
        expected = {
            'name': 'Test name',
            'app_slug': 'testname',
            'summary': 'Hello!',
            'description': 'desc',
            'privacy_policy': 'XXX &lt;script&gt;alert("xss")&lt;/script&gt;',
        }
        expected.update(expected)

        for field, expected in expected.iteritems():
            got = unicode(getattr(addon, field))
            eq_(got, expected,
                'Expected %r for %r. Got %r.' % (expected, field, got))
        eq_(list(addon.device_types), [self.dtype])

    def test_success(self):
        self._step()
        data = self.get_dict()
        # Post and be redirected.
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)
        self.check_dict(data=data)
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('payments'))

    def test_disabled_payments_success(self):
        self.create_switch(name='disabled-payments')
        self._step()
        data = self.get_dict()
        r = self.client.post(self.url, data)
        self.assertNoFormErrors(r)
        self.check_dict(data=data)
        self.webapp = self.get_webapp()
        self.assert3xx(r, self.get_url('done'))

    def test_no_video_types(self):
        self._step()
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('.screenshot_upload').attr('data-allowed-types'),
            'image/jpeg|image/png')
        eq_(doc('#id_icon_upload').attr('data-allowed-types'),
            'image/jpeg|image/png')

    def test_video_types(self):
        self.create_switch(name='video-upload')
        self._step()
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('.screenshot_upload').attr('data-allowed-types'),
            'image/jpeg|image/png|video/webm')

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

    def _setup_other_webapp(self):
        self._step()
        # Generate another webapp to test name uniqueness.
        app = amo.tests.addon_factory(type=amo.ADDON_WEBAPP, name='Cool App')
        eq_(ReverseNameLookup(webapp=True).get(app.name), app.id)

    def test_name_unique(self):
        self._setup_other_webapp()
        r = self.client.post(self.url, self.get_dict(name='Cool App'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form_basic', 'name', error)

    def test_name_unique_strip(self):
        # Make sure we can't sneak in a name by adding a space or two.
        self._setup_other_webapp()
        r = self.client.post(self.url, self.get_dict(name='  Cool App  '))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form_basic', 'name', error)

    def test_name_unique_case(self):
        # Make sure unique names aren't case sensitive.
        self._setup_other_webapp()
        r = self.client.post(self.url, self.get_dict(name='cool app'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form_basic', 'name', error)

    def test_name_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(name=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'name',
                             'This field is required.')

    def test_screenshot_required(self):
        self._step()
        data = self.get_dict()
        for k in data:
            if k.startswith('files') and k.endswith('upload_hash'):
                data[k] = ''
        rp = self.client.post(self.url, data)
        eq_(rp.context['form_previews'].non_form_errors(),
            ['You must upload at least one screenshot.'])

    def test_screenshot_or_video_required(self):
        self.create_switch(name='video-upload')
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

    def test_name_length(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(name='a' * 129))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'name',
            'Ensure this value has at most 128 characters (it has 129).')

    def test_slug_invalid(self):
        self._step()
        # Submit an invalid slug.
        d = self.get_dict(slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'slug',
            "Enter a valid 'slug' consisting of letters, numbers, underscores "
            "or hyphens.")

    def test_slug_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(slug=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'slug',
                             'This field is required.')

    def test_summary_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(summary=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'summary',
                             'This field is required.')

    def test_summary_length(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(summary='a' * 251))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form_basic', 'summary',
            'Ensure this value has at most 250 characters (it has 251).')

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

    def test_device_types_required(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(device_types=None))
        self.assertFormError(r, 'form_devices', 'device_types',
                             'This field is required.')

    def test_device_types_invalid(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(device_types='999'))
        self.assertFormError(r, 'form_devices', 'device_types',
            'Select a valid choice. 999 is not one of the available choices.')

    def test_device_types_default(self):
        self._step()
        # Add the rest of the device types. We already add [0] in _step().
        for d_id in DEVICE_TYPES.keys()[1:]:
            AddonDeviceType.objects.create(addon=self.webapp,
                                           device_type=d_id)

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        checkboxes = pq(r.content)('input[name=device_types]')
        eq_(checkboxes.filter(':checked').length, checkboxes.length,
            'All device types should be checked by default.')

    def test_device_types_default_on_post(self):
        self._step()
        r = self.client.post(self.url, self.get_dict(device_types=None))
        eq_(r.status_code, 200)
        checkboxes = pq(r.content)('input[name=device_types]')
        eq_(checkboxes.filter(':checked').length, 0,
            'POSTed values should not get replaced by the defaults.')

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


class TestPayments(TestSubmit):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestPayments, self).setUp()
        self.webapp = self.get_webapp()
        self.webapp.update(status=amo.STATUS_NULL)
        self.url = self.get_url('payments')
        self.price = Price.objects.create(price='1.00')
        self._step()

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def _step(self):
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp,
            terms=True, manifest=True, details=True)
        AddonUser.objects.create(addon=self.webapp, user=self.user)

    def test_anonymous(self):
        self._test_anonymous()

    def test_required(self):
        res = self.client.post(self.url, {'premium_type': ''})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'premium_type',
                             'This field is required.')

    def test_premium_type_not_valid(self):
        res = self.client.post(self.url, {'premium_type': 124})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'premium_type',
            'Select a valid choice. 124 is not one of the available choices.')

    def test_premium_type_valid(self):
        res = self.client.post(self.url, {'premium_type': amo.ADDON_PREMIUM})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM)

    def _test_valid(self, expected_status):
        res = self.client.post(self.get_url('payments'),
                               {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('done'))
        eq_(self.get_webapp().status, expected_status)

    def test_valid_pending(self):
        res = self.client.post(self.get_url('payments'),
                               {'premium_type': amo.ADDON_FREE})
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('done'))
        eq_(self.get_webapp().status, amo.WEBAPPS_UNREVIEWED_STATUS)

    def test_premium(self):
        for type_ in [amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP]:
            res = self.client.post(self.get_url('payments'),
                                  {'premium_type': type_})
            eq_(res.status_code, 302)
            self.assert3xx(res, self.get_url('payments.upsell'))

    def test_free_inapp(self):
        res = self.client.post(self.get_url('payments'),
                               {'premium_type': amo.ADDON_FREE_INAPP})
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('payments.paypal'))

    def test_premium_other(self):
        res = self.client.post(self.get_url('payments'),
                               {'premium_type': amo.ADDON_OTHER_INAPP})
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('done'))

    def test_price(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'),
                               {'price': self.price.pk})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium.price.pk, self.price.pk)
        self.assert3xx(res, self.get_url('payments.paypal'))

    def _make_upsell(self):
        free = Addon.objects.create(type=amo.ADDON_WEBAPP)
        free.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=free, user=self.user)
        return free

    def test_immediate(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'),
                               {'price': self.price.pk,
                                'make_public': 0})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().make_public, amo.PUBLIC_IMMEDIATELY)

    def test_wait(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'),
                               {'price': self.price.pk,
                                'make_public': 1})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().make_public, amo.PUBLIC_WAIT)

    def test_upsell_states(self):
        free = self._make_upsell()
        free.update(status=amo.STATUS_NULL)
        res = self.client.get(self.get_url('payments.upsell'))
        eq_(len(res.context['form'].fields['free'].choices), 0)

    def test_upsell_states_inapp(self):
        free = self._make_upsell()
        free.update(premium_type=amo.ADDON_FREE_INAPP)
        res = self.client.get(self.get_url('payments.upsell'))
        eq_(len(res.context['form'].fields['free'].choices), 1)

    def test_upsell(self):
        free = self._make_upsell()
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'),
                               {'price': self.price.pk,
                                'do_upsell': 1,
                                'free': free.pk,
                                'text': 'some upsell',
                                })
        eq_(self.get_webapp().premium.price.pk, self.price.pk)
        eq_(self.get_webapp().upsold.free.pk, free.pk)
        eq_(self.get_webapp().upsold.premium.pk, self.get_webapp().pk)
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('payments.paypal'))

    def test_no_upsell(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(self.get_url('payments.upsell'),
                               {'price': self.price.pk})
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('div.brform')), 3)

    def test_upsell_missing(self):
        free = Addon.objects.create(type=amo.ADDON_WEBAPP)
        AddonUser.objects.create(addon=free, user=self.user)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'),
                               {'price': self.price.pk,
                                'do_upsell': 1,
                                })
        eq_(res.status_code, 200)

    def test_bad_upsell(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.upsell'), {'price': ''})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'price', 'This field is required.')

    def test_paypal(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.paypal'),
                               {'business_account': 'yes',
                                'email': 'foo@bar.com'})
        eq_(self.get_webapp().paypal_id, 'foo@bar.com')
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('payments.bounce'))

    @mock.patch('mkt.submit.views.client')
    def test_paypal_solitude(self, client):
        self.create_flag(name='solitude-payments')
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.paypal'),
                               {'business_account': 'yes',
                                'email': 'foo@bar.com'})
        eq_(client.create_seller_paypal.call_args[0][0], self.webapp)
        eq_(client.patch_seller_paypal.call_args[1]['data']['paypal_id'],
            'foo@bar.com')
        client.post_permissions_url.return_value = {'token': 'http://foo/'}
        self.assert3xx(res, self.get_url('payments.bounce'))

    @mock.patch('mkt.submit.views.client')
    def test_bounce_solitude(self, client):
        self.create_flag(name='solitude-payments')
        url = 'http://foo.com'
        client.post_permission_url.return_value = {'token': url}
        res = self.client.post(self.get_url('payments.bounce'))
        eq_(pq(res.content)('section.primary a.button').attr('href'), url)

    def test_no_paypal(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.paypal'),
                               {'business_account': 'no'})
        eq_(res.status_code, 302)
        eq_(res._headers['location'][1], settings.PAYPAL_CGI_URL)

    def test_later_paypal(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.get_url('payments.paypal'),
                               {'business_account': 'later'})
        eq_(res.status_code, 302)
        self.assert3xx(res, self.get_url('done'))

    def get_acquire_url(self):
        url = self.webapp.get_dev_url('acquire_refund_permission')
        return urlparams(url, dest='submission', request_token='foo',
                         verification_code='foo')

    @mock.patch('paypal.get_permissions_token')
    @mock.patch('paypal.get_personal_data')
    def test_bounce_result_works(self, get_personal_data,
                                 get_permissions_token):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           paypal_id='a@a.com')
        get_permissions_token.return_value = 'foo'
        get_personal_data.return_value = {'email': 'a@a.com'}
        res = self.client.get(self.get_acquire_url())
        self.assert3xx(res, self.get_url('payments.confirm'))

    @mock.patch('mkt.submit.views.client')
    def test_confirm_solitude(self, client):
        self.create_flag(name='solitude-payments')
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           paypal_id='a@a.com')
        client.get_seller_paypal_if_exists.return_value = {'country': 'fr'}
        res = self.client.get(self.get_url('payments.confirm'))
        eq_(res.context['form'].data['country'], 'fr')

    @mock.patch('mkt.submit.views.client')
    def test_confirm_solitude_saves(self, client):
        self.create_flag(name='solitude-payments')
        client.get_seller_paypal_if_exists.return_value = None
        client.create_seller_for_pay.return_value = 1
        res = self.client.post(self.get_url('payments.confirm'),
                               {'country': 'uk',
                                'address_one': '123 bob st.'})
        args = client.patch_seller_paypal.call_args[1]
        eq_(args['data']['address_one'], '123 bob st.')
        eq_(args['pk'], 1)
        eq_(res.status_code, 302)

    @mock.patch('paypal.get_permissions_token')
    @mock.patch('paypal.get_personal_data')
    def test_bounce_result_fails_email(self, get_personal_data,
                                 get_permissions_token):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           paypal_id='b@b.com')
        get_permissions_token.return_value = 'foo'
        get_personal_data.return_value = {'email': 'a@a.com'}
        res = self.client.get(self.get_acquire_url())
        self.assert3xx(res, self.get_url('payments.paypal'))

    @mock.patch('paypal.get_permissions_token')
    def test_bounce_result_fails_paypal_error(self, get_permissions_token):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        get_permissions_token.side_effect = paypal.PaypalError
        res = self.client.get(self.get_acquire_url())
        eq_(res.status_code, 500)
        self.assertTemplateUsed(res, 'site/500_paypal.html')

        doc = pq(res.content)
        eq_(doc('div.prose form a').attr('href'),
            self.get_url('payments.bounce'))
        eq_(doc('div.prose form').attr('action'),
            self.get_url('payments.paypal'))


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
                    details=True, payments=True)
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
