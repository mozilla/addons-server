from datetime import datetime
import json

from django import test

from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.urlresolvers import reverse
from addons.models import Addon
from applications.models import AppVersion, Application
from files.models import Approval, FileValidation, File
from versions.models import Version, VersionSummary
from zadmin.models import ValidationJob, ValidationResult


class TestFlagged(test_utils.TestCase):
    fixtures = ['zadmin/tests/flagged']

    def setUp(self):
        super(TestFlagged, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def test_get(self):
        url = reverse('zadmin.flagged')
        response = self.client.get(url, follow=True)

        addons = dict((a.id, a) for a in response.context['addons'])
        eq_(len(addons), 3)

        # 1. an addon should have latest version and approval attached
        addon = Addon.objects.get(id=1)
        eq_(addons[1], addon)
        eq_(addons[1].version.id,
            Version.objects.filter(addon=addon).latest().id)
        eq_(addons[1].approval.id,
            Approval.objects.filter(addon=addon).latest().id)

        # 2. missing approval is ok
        addon = Addon.objects.get(id=2)
        eq_(addons[2], addon)
        eq_(addons[2].version.id,
            Version.objects.filter(addon=addon).latest().id)
        eq_(addons[2].approval, None)

        # 3. missing approval is ok
        addon = Addon.objects.get(id=3)
        eq_(addons[3], addon)
        eq_(addons[3].approval.id,
            Approval.objects.filter(addon=addon).latest().id)
        eq_(addons[3].version, None)

    def test_post(self):
        # Do a get first so the query is cached.
        url = reverse('zadmin.flagged')
        self.client.get(url, follow=True)

        response = self.client.post(url, {'addon_id': ['1', '2']}, follow=True)
        self.assertRedirects(response, url)

        assert not Addon.objects.get(id=1).admin_review
        assert not Addon.objects.get(id=2).admin_review

        addons = response.context['addons']
        eq_(len(addons), 1)
        eq_(addons[0], Addon.objects.get(id=3))


class TestBulkValidation(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/appversion', 'base/users']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.get_version()
        app = Application.objects.get(pk=amo.FIREFOX.id)
        # pretend this version supports all Firefox versions:
        for av in AppVersion.objects.filter(application=app):
            VersionSummary.objects.create(application=app,
                                          version=self.version,
                                          addon=self.addon,
                                          max=av.id)

    def appversion(self, version, application=amo.FIREFOX.id):
        return AppVersion.objects.get(application=application,
                                      version=version)

    def test_start(self):
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.appversion('3.5.*').id,
                              'target_version': self.appversion('3.6.*').id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        if 'form' in r.context:
            eq_(r.context['form'].errors.as_text(), '')
        self.assertRedirects(r, reverse('zadmin.validation'))
        job = ValidationJob.objects.get()
        eq_(job.application_id, amo.FIREFOX.id)
        eq_(job.curr_max_version.version, '3.5.*')
        eq_(job.target_version.version, '3.6.*')
        eq_(job.finish_email, 'fliggy@mozilla.com')
        eq_(job.completed, None)
        eq_(job.result_set.all().count(),
            len(self.version.all_files))

    def test_grid(self):
        kw = dict(application_id=amo.FIREFOX.id,
                  curr_max_version=self.appversion('3.5.*'),
                  target_version=self.appversion('3.6.*'))
        job = ValidationJob.objects.create(**kw)
        for i, res in enumerate((dict(errors=0), dict(errors=1))):
            f = File.objects.create(version=self.version,
                                    filename='file-%s' % i,
                                    platform_id=amo.PLATFORM_ALL.id,
                                    status=amo.STATUS_PUBLIC)
            kw = dict(file=f,
                      validation='{}',
                      errors=0,
                      warnings=0,
                      notices=0)
            kw.update(res)
            res['valid'] = kw['errors'] == 0
            fv = FileValidation.objects.create(**kw)
            ValidationResult.objects.create(file_validation=fv,
                                            validation_job=job,
                                            task_error=None,
                                            completed=datetime.now())
        r = self.client.get(reverse('zadmin.validation'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('table tr td').eq(2).text(), '3.5.*')
        eq_(doc('table tr td').eq(3).text(), '3.6.*')
        eq_(doc('table tr td').eq(4).text(), '2')
        eq_(doc('table tr td').eq(5).text(), '1')
        eq_(doc('table tr td').eq(6).text(), '1')

    def test_application_versions_json(self):
        r = self.client.post(reverse('zadmin.application_versions_json'),
                             {'application_id': amo.FIREFOX.id})
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        empty = True
        for id, ver in data['choices']:
            empty = False
            eq_(AppVersion.objects.get(pk=id).version, ver)
        assert not empty, "Unexpected: %r" % data


def test_settings():
    # Are you there, settings page?
    response = test.Client().get(reverse('zadmin.settings'), follow=True)
    eq_(response.status_code, 200)
