import json
import os

from django.conf import settings

import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon, AddonDeviceType, AddonUser, DeviceType
from addons.utils import ReverseNameLookup
from files.tests.test_models import UploadTest as BaseUploadTest
import mkt
from mkt.submit.models import AppSubmissionChecklist
from translations.models import Translation
from users.models import UserProfile
from webapps.models import Webapp


class TestSubmit(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = self.get_user()
        assert self.client.login(username=self.user.email, password='password')

    def get_user(self):
        return UserProfile.objects.get(username='regularuser')

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

        # Check the current step.
        eq_(progress.find('.current').text(),
            unicode(mkt.APP_STEPS_TITLE[current]))


class TestTerms(TestSubmit):
    fixtures = ['base/users']

    def setUp(self):
        super(TestTerms, self).setUp()
        self.url = reverse('submit.app.terms')

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def test_jump_to_step(self):
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assertRedirects(r, self.url)

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#submit-terms').length, 1)

    def test_progress_display(self):
        self._test_progress_display([], 'terms')

    def test_agree(self):
        r = self.client.post(self.url, {'read_dev_agreement': True})
        self.assertRedirects(r, reverse('submit.app.manifest'))
        eq_(self.get_user().read_dev_agreement, True)

    def test_disagree(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 200)
        eq_(self.user.read_dev_agreement, False)


class TestManifest(TestSubmit):
    fixtures = ['base/users']

    def setUp(self):
        super(TestManifest, self).setUp()
        self.url = reverse('submit.app.manifest')

    def _step(self):
        self.user.update(read_dev_agreement=True)

    def test_anonymous(self):
        self._test_anonymous()

    def test_cannot_skip_prior_step(self):
        r = self.client.get(self.url, follow=True)
        # And we start back at one...
        self.assertRedirects(r, reverse('submit.app.terms'))

    def test_jump_to_step(self):
        # I already read the Terms.
        self._step()
        # So jump me to the Manifest step.
        r = self.client.get(reverse('submit.app'), follow=True)
        self.assertRedirects(r, reverse('submit.app.manifest'))

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
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        self.manifest = os.path.join(settings.ROOT, 'mkt', 'submit', 'tests',
                                     'webapps', 'mozball.webapp')
        self.upload = self.get_upload(abspath=self.manifest)
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

    def test_page_title(self):
        eq_(pq(self.client.get(self.url).content)('title').text(),
            'App Manifest | Developer Hub | Mozilla Marketplace')

    def test_post_app_redirect(self):
        r = self.post()
        webapp = Webapp.objects.get()
        self.assertRedirects(r,
            reverse('submit.app.details', args=[webapp.app_slug]))

    def test_app_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.type, amo.ADDON_WEBAPP)
        eq_(addon.guid, None)
        eq_(unicode(addon.name), 'MozillaBall')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, 'mozillaball')
        eq_(addon.summary, u'Exciting Open Web development action!')
        eq_(Translation.objects.get(id=addon.summary.id, locale='it'),
            u'Azione aperta emozionante di sviluppo di fotoricettore!')

    def test_version_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.current_version.version, '1.0')

    def test_file_from_uploaded_manifest(self):
        addon = self.post_addon()
        files = addon.current_version.files.all()
        eq_(len(files), 1)
        eq_(files[0].status, amo.STATUS_PUBLIC)


class TestCreateWebAppFromManifest(BaseWebAppTest):

    def setUp(self):
        super(TestCreateWebAppFromManifest, self).setUp()
        Webapp.objects.create(app_slug='xxx', app_domain='existing-app.com')

    def upload_webapp(self, manifest_url, **post_kw):
        self.upload.update(name=manifest_url)  # Simulate JS upload.
        return self.post(**post_kw)

    def post_manifest(self, manifest_url):
        rs = self.client.post(reverse('mkt.developers.upload_manifest'),
                              dict(manifest=manifest_url))
        if 'json' in rs['content-type']:
            rs = json.loads(rs.content)
        return rs

    @mock.patch.object(settings, 'WEBAPPS_UNIQUE_BY_DOMAIN', True)
    def test_duplicate_domain(self):
        rs = self.upload_webapp('http://existing-app.com/my.webapp',
                                expect_errors=True)
        eq_(rs.context['form'].errors,
            {'upload':
             ['An app already exists on this domain; only one '
              'app per domain is allowed.']})

    @mock.patch.object(settings, 'WEBAPPS_UNIQUE_BY_DOMAIN', False)
    def test_allow_duplicate_domains(self):
        self.upload_webapp('http://existing-app.com/my.webapp')  # No errors.

    @mock.patch.object(settings, 'WEBAPPS_UNIQUE_BY_DOMAIN', True)
    def test_duplicate_domain_from_js(self):
        data = self.post_manifest('http://existing-app.com/my.webapp')
        eq_(data['validation']['errors'], 1)
        eq_(data['validation']['messages'][0]['message'],
            'An app already exists on this domain; '
            'only one app per domain is allowed.')

    @mock.patch.object(settings, 'WEBAPPS_UNIQUE_BY_DOMAIN', False)
    def test_allow_duplicate_domains_from_js(self):
        rs = self.post_manifest('http://existing-app.com/my.webapp')
        eq_(rs.status_code, 302)


class TestDetails(TestSubmit):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestDetails, self).setUp()
        self.webapp = self.get_webapp()
        self.url = reverse('submit.app.details', args=[self.webapp.app_slug])

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def _step(self):
        self.user.update(read_dev_agreement=True)
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp,
            terms=True, manifest=True)

        # Associate app with user.
        AddonUser.objects.create(addon=self.webapp, user=self.user)

        # Associate device type with app.
        self.dtype = DeviceType.objects.create(name='fligphone')
        AddonDeviceType.objects.create(addon=self.webapp,
                                       device_type=self.dtype)

    def test_anonymous(self):
        self._test_anonymous()

    def test_resume_step(self):
        self._step()
        payments_url = reverse('submit.app.payments',
                               args=[self.webapp.app_slug])
        r = self.client.get(payments_url, follow=True)
        self.assertRedirects(r, reverse('submit.app.details',
                                        args=[self.webapp.app_slug]))

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

    def get_dict(self, **kw):
        data = {
            'name': 'Test name',
            'slug': 'testname',
            'summary': 'Hello!',
            'description': 'desc',
            'privacy_policy': 'XXX <script>alert("xss")</script>',
            'device_types': [self.dtype.id],
        }
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
        # Post and be redirected.
        r = self.client.post(self.url, self.get_dict())
        self.assertNoFormErrors(r)
        # TODO: Assert redirects when we go to next step.
        self.check_dict()

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


class TestPayments(TestSubmit):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestPayments, self).setUp()
        self.webapp = self.get_webapp()
        self.url = reverse('submit.app.payments', args=[self.webapp.app_slug])

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def _step(self):
        self.user.update(read_dev_agreement=True)
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp,
            terms=True, manifest=True, details=True)
        AddonUser.objects.create(addon=self.webapp, user=self.user)

    def test_anonymous(self):
        self._test_anonymous()

    def test_required(self):
        self._step()
        res = self.client.post(self.url, {'premium_type': ''})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'premium_type',
                             'This field is required.')

    def test_not_valid(self):
        self._step()
        res = self.client.post(self.url, {'premium_type': 124})
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'premium_type',
            'Select a valid choice. 124 is not one of the available choices.')

    def test_valid(self):
        self._step()
        res = self.client.post(self.url, {'premium_type': amo.ADDON_PREMIUM})
        eq_(res.status_code, 302)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM)


class TestDone(TestSubmit):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestDone, self).setUp()
        self.webapp = self.get_webapp()
        self.url = reverse('submit.app.done', args=[self.webapp.app_slug])

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def _step(self):
        self.user.update(read_dev_agreement=True)
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp,
            terms=True, manifest=True, details=True, payments=True)
        AddonUser.objects.create(addon=self.webapp, user=self.user)

    def test_anonymous(self):
        self._test_anonymous()

    def test_done(self):
        self._step()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_payments(self):
        self._step()
        self.get_webapp().update(premium_type=amo.ADDON_PREMIUM_INAPP)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('p.paypal-notes')), 1)
