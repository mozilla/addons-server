from datetime import datetime
import json

from django import test

import mock
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

import amo
from amo.tests import close_to_now, assert_no_validation_errors
from amo.urlresolvers import reverse
from addons.models import Addon
from applications.models import AppVersion
from devhub.models import ActivityLog
from files.models import Approval, File
from versions.models import Version
from zadmin.models import ValidationJob, ValidationResult
from zadmin.views import completed_versions_dirty


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


class BulkValidationTest(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/appversion',
                'base/users']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.get_version()
        self.curr_max = self.appversion('3.7a1pre')
        self.counter = 0

    def appversion(self, version, application=amo.FIREFOX.id):
        return AppVersion.objects.get(application=application,
                                      version=version)

    def create_job(self, **kwargs):
        kw = dict(application_id=amo.FIREFOX.id,
                  curr_max_version=self.curr_max,
                  target_version=self.appversion('3.7a3'))
        kw.update(kwargs)
        return ValidationJob.objects.create(**kw)

    def create_file(self, version=None):
        if not version:
            version = self.version
        return File.objects.create(version=version,
                                   filename='file-%s' % self.counter,
                                   platform_id=amo.PLATFORM_ALL.id,
                                   status=amo.STATUS_PUBLIC)

    def create_result(self, job, f, **kwargs):
        self.counter += 1
        kw = dict(file=f,
                  validation='{}',
                  errors=0,
                  warnings=0,
                  notices=0,
                  validation_job=job,
                  task_error=None,
                  valid=0,
                  completed=datetime.now())
        kw.update(kwargs)
        return ValidationResult.objects.create(**kw)


class TestBulkValidation(BulkValidationTest):

    @mock.patch('zadmin.tasks.bulk_validate_file')
    def test_start(self, bulk_validate_file):
        new_max = self.appversion('3.7a3')
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        if 'form' in r.context:
            eq_(r.context['form'].errors.as_text(), '')
        self.assertRedirects(r, reverse('zadmin.validation'))
        job = ValidationJob.objects.get()
        eq_(job.application_id, amo.FIREFOX.id)
        eq_(job.curr_max_version.version, self.curr_max.version)
        eq_(job.target_version.version, new_max.version)
        eq_(job.finish_email, 'fliggy@mozilla.com')
        eq_(job.completed, None)
        eq_(job.result_set.all().count(),
            len(self.version.all_files))
        assert bulk_validate_file.delay.called

    def test_grid(self):
        job = self.create_job()
        for res in (dict(errors=0), dict(errors=1)):
            self.create_result(job, self.create_file(), **res)

        r = self.client.get(reverse('zadmin.validation'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('table tr td').eq(2).text(), self.curr_max.version)
        eq_(doc('table tr td').eq(3).text(), '3.7a3')
        eq_(doc('table tr td').eq(4).text(), '2')
        eq_(doc('table tr td').eq(5).text(), '1')
        eq_(doc('table tr td').eq(6).text()[0], '1')
        eq_(doc('table tr td').eq(7).text(), '0')

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


class TestBulkUpdate(BulkValidationTest):

    def setUp(self):
        super(TestBulkUpdate, self).setUp()

        self.job = self.create_job()
        self.update_url = reverse('zadmin.set-max-version', args=[self.job.pk])
        self.list_url = reverse('zadmin.validation')

        self.version_one = Version.objects.create(addon=self.addon)
        self.version_one
        self.version_two = Version.objects.create(addon=self.addon)

    def test_no_update_link(self):
        self.create_result(self.job, self.create_file(), **{})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a').text(), 'Set max version')

    def test_update_link(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a').text(), 'Set max version')

    def test_update_url(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a').attr('data-job-url'), self.update_url)

    def test_update_anonymous(self):
        self.client.logout()
        r = self.client.post(self.update_url)
        eq_(r.status_code, 302)

    def test_version_pks(self):
        for version in [self.version_one, self.version_two]:
            for x in range(0, 3):
                self.create_result(self.job, self.create_file(version))

        eq_(sorted(completed_versions_dirty(self.job)),
            [self.version_one.pk, self.version_two.pk])

    def test_update_passing_only(self):
        self.create_result(self.job, self.create_file(self.version_one))
        self.create_result(self.job, self.create_file(self.version_two),
                           errors=1)
        eq_(sorted(completed_versions_dirty(self.job)),
            [self.version_one.pk])

    def test_update_pks(self):
        self.create_result(self.job, self.create_file(self.version))
        r = self.client.post(self.update_url)
        eq_(r.status_code, 302)
        eq_(self.version.apps.all()[0].max,
            self.job.target_version)

    def test_update_unclean_pks(self):
        self.create_result(self.job, self.create_file(self.version))
        self.create_result(self.job, self.create_file(self.version),
                           errors=1)
        r = self.client.post(self.update_url)
        eq_(r.status_code, 302)
        eq_(self.version.apps.all()[0].max, self.job.curr_max_version)

    def test_update_pks_logs(self):
        self.create_result(self.job, self.create_file(self.version))
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 0)
        self.client.post(self.update_url)
        upd = amo.LOG.BULK_VALIDATION_UPDATED.id
        eq_((ActivityLog.objects.for_addons(self.addon)
                                .filter(action=upd).count()), 1)

    def test_update_wrong_version(self):
        self.create_result(self.job, self.create_file(self.version))
        av = self.version.apps.all()[0]
        av.max = self.appversion('3.6')
        av.save()
        self.client.post(self.update_url)
        eq_(self.version.apps.all()[0].max, self.appversion('3.6'))


class TestBulkValidationTask(BulkValidationTest):

    def start_validation(self):
        self.new_max = self.appversion('3.7a3')
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': self.new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        eq_(r.status_code, 200)

    @attr('validator')
    def test_validate(self):
        self.start_validation()
        res = ValidationResult.objects.get()
        assert close_to_now(res.completed)
        assert_no_validation_errors(res)
        eq_(res.errors, 1)  # package could not be found
        eq_(res.valid, False)
        eq_(res.warnings, 0)
        eq_(res.notices, 0)
        v = json.loads(res.validation)
        eq_(v['errors'], 1)
        assert close_to_now(res.validation_job.completed)
        eq_(res.validation_job.stats['total'], 1)
        eq_(res.validation_job.stats['completed'], 1)
        eq_(res.validation_job.stats['passing'], 0)
        eq_(res.validation_job.stats['failing'], 1)
        eq_(res.validation_job.stats['errors'], 0)

    @mock.patch('zadmin.tasks.run_validator')
    def test_task_error(self, run_validator):
        run_validator.side_effect = RuntimeError('validation error')
        self.start_validation()
        res = ValidationResult.objects.get()
        err = res.task_error.strip()
        assert err.endswith('RuntimeError: validation error'), (
                                                    'Unexpected: %s' % err)
        assert close_to_now(res.completed)
        eq_(res.validation_job.stats['total'], 1)
        eq_(res.validation_job.stats['errors'], 1)

    @mock.patch('zadmin.tasks.run_validator')
    def test_validate_for_appversions(self, run_validator):
        self.start_validation()
        assert run_validator.called
        eq_(run_validator.call_args[1]['for_appversions'],
            {amo.FIREFOX.guid: [self.new_max.version]})


def test_settings():
    # Are you there, settings page?
    response = test.Client().get(reverse('zadmin.settings'), follow=True)
    eq_(response.status_code, 200)
