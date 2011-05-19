# -*- coding: utf-8 -*-
import csv
from cStringIO import StringIO
from datetime import datetime
import json

from django import test
from django.core import mail

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
from users.models import UserProfile
from versions.models import Version
from zadmin.forms import NotifyForm
from zadmin.models import ValidationJob, ValidationResult, EmailPreviewTopic
from zadmin.views import completed_versions_dirty, find_files
from zadmin import tasks


no_op_validation = dict(errors=0, warnings=0, notices=0,
                        compatibility_summary=dict(errors=0, warnings=0,
                                                   notices=0))


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
        self.creator = UserProfile.objects.get(username='editor')
        self.version = self.addon.get_version()
        self.curr_max = self.appversion('3.7a1pre')
        self.counter = 0

    def appversion(self, version, application=amo.FIREFOX.id):
        return AppVersion.objects.get(application=application,
                                      version=version)

    def create_job(self, **kwargs):
        kw = dict(application_id=amo.FIREFOX.id,
                  curr_max_version=self.curr_max,
                  target_version=self.appversion('3.7a3'),
                  creator=self.creator)
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

    def assertNoFormErrors(self, r):
        if 'form' in r.context:
            eq_(r.context['form'].errors.as_text(), '')

    @mock.patch('zadmin.tasks.bulk_validate_file')
    def test_start(self, bulk_validate_file):
        new_max = self.appversion('3.7a3')
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
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

    @mock.patch('zadmin.tasks.bulk_validate_file')
    def test_ignore_user_disabled_addons(self, bulk_validate_file):
        self.addon.update(disabled_by_user=True)
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': self.appversion('3.7a3').id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assertRedirects(r, reverse('zadmin.validation'))
        assert not bulk_validate_file.delay.called

    @mock.patch('zadmin.tasks.bulk_validate_file')
    def test_ignore_non_public_addons(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        for status in (amo.STATUS_DISABLED, amo.STATUS_NULL):
            self.addon.update(status=status)
            r = self.client.post(reverse('zadmin.start_validation'),
                                 {'application': amo.FIREFOX.id,
                                  'curr_max_version': self.curr_max.id,
                                  'target_version': target_ver,
                                  'finish_email': 'fliggy@mozilla.com'},
                                 follow=True)
            self.assertNoFormErrors(r)
            self.assertRedirects(r, reverse('zadmin.validation'))
            assert not bulk_validate_file.delay.called, (
                            'Addon with status %s should be ignored' % status)

    @mock.patch('zadmin.tasks.bulk_validate_file')
    def test_validate_all_non_disabled_addons(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        for status in (amo.STATUS_PUBLIC, amo.STATUS_LISTED):
            bulk_validate_file.delay.called = False
            self.addon.update(status=status)
            r = self.client.post(reverse('zadmin.start_validation'),
                                 {'application': amo.FIREFOX.id,
                                  'curr_max_version': self.curr_max.id,
                                  'target_version': target_ver,
                                  'finish_email': 'fliggy@mozilla.com'},
                                 follow=True)
            self.assertNoFormErrors(r)
            self.assertRedirects(r, reverse('zadmin.validation'))
            assert bulk_validate_file.delay.called, (
                        'Addon with status %s should be validated' % status)

    def test_grid(self):
        job = self.create_job()
        for res in (dict(errors=0), dict(errors=1)):
            self.create_result(job, self.create_file(), **res)

        r = self.client.get(reverse('zadmin.validation'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('table tr td').eq(2).text(), self.curr_max.version)
        eq_(doc('table tr td').eq(3).text(), '3.7a3')
        eq_(doc('table tr td').eq(4).text(), '2')  # tested
        eq_(doc('table tr td').eq(5).text(), '1')  # failing
        eq_(doc('table tr td').eq(6).text()[0], '1')  # passing
        eq_(doc('table tr td').eq(7).text(), '0')  # exceptions

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

        self.job = self.create_job(completed=datetime.now())
        self.update_url = reverse('zadmin.notify.success', args=[self.job.pk])
        self.list_url = reverse('zadmin.validation')
        self.data = {'text': '{{ APPLICATION }} {{ VERSION }}',
                     'subject': '..'}

        self.version_one = Version.objects.create(addon=self.addon)
        self.version_two = Version.objects.create(addon=self.addon)

    def test_no_update_link(self):
        self.create_result(self.job, self.create_file(), **{})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a.set-max-version').text(), 'Set max version')

    def test_update_link(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a.set-max-version').text(), 'Set max version')

    def test_update_url(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a.set-max-version').attr('data-job-url'),
            self.update_url)

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
        r = self.client.post(self.update_url, self.data)
        eq_(r.status_code, 302)
        eq_(self.version.apps.all()[0].max, self.job.target_version)

    def test_update_unclean_pks(self):
        self.create_result(self.job, self.create_file(self.version))
        self.create_result(self.job, self.create_file(self.version),
                           errors=1)
        r = self.client.post(self.update_url, self.data)
        eq_(r.status_code, 302)
        eq_(self.version.apps.all()[0].max, self.job.curr_max_version)

    def test_update_pks_logs(self):
        self.create_result(self.job, self.create_file(self.version))
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 0)
        self.client.post(self.update_url, self.data)
        upd = amo.LOG.BULK_VALIDATION_UPDATED.id
        logs = ActivityLog.objects.for_addons(self.addon).filter(action=upd)
        eq_(logs.count(), 1)
        eq_(logs[0].user, self.creator)

    def test_update_wrong_version(self):
        self.create_result(self.job, self.create_file(self.version))
        av = self.version.apps.all()[0]
        av.max = self.appversion('3.6')
        av.save()
        self.client.post(self.update_url, self.data)
        eq_(self.version.apps.all()[0].max, self.appversion('3.6'))

    def test_update_different_app(self):
        self.create_result(self.job, self.create_file(self.version))
        target = self.version.apps.all()[0]
        target.application_id = amo.FIREFOX.id
        target.save()
        eq_(self.version.apps.all()[0].max, self.curr_max)

    def test_update_twice(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        eq_(self.version.apps.all()[0].max, self.job.target_version)
        now = self.version.modified
        self.client.post(self.update_url, self.data)
        eq_(self.version.modified, now)

    def test_update_notify(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        eq_(len(mail.outbox), 1)

    def test_update_subject(self):
        data = self.data.copy()
        data['subject'] = '{{ ADDON_NAME }}{{ ADDON_VERSION }}'
        f = self.create_file(self.version)
        self.create_result(self.job, f)
        self.client.post(self.update_url, data)
        eq_(mail.outbox[0].subject,
            '%s%s' % (self.addon.name, f.version.version))

    def test_application_version(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        eq_(mail.outbox[0].body, 'Firefox 3.7a3')

    def test_multiple_result_links(self):
        # Creates validation results for two files of the same addon:
        results = [
            self.create_result(self.job, self.create_file(self.version)),
            self.create_result(self.job, self.create_file(self.version))]
        self.client.post(self.update_url, {'text': '{{ RESULT_LINKS }}',
                                           'subject': '..'})
        links = mail.outbox[0].body.split(' ')
        for result in results:
            assert any(ln.endswith(reverse('devhub.validation_result',
                                           args=(self.addon.slug, result.pk)))
                       for ln in links), ('Unexpected links: %s' % links)

    def test_notify_mail_preview(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url,
                         {'text': 'the message', 'subject': 'the subject',
                          'preview_only': 'on'})
        eq_(len(mail.outbox), 0)
        rs = self.job.get_success_preview_emails()
        eq_([e.subject for e in rs], ['the subject'])


class TestBulkNotify(BulkValidationTest):

    def setUp(self):
        super(TestBulkNotify, self).setUp()

        self.job = self.create_job(completed=datetime.now())
        self.update_url = reverse('zadmin.notify.failure', args=[self.job.pk])
        self.syntax_url = reverse('zadmin.notify.syntax')
        self.list_url = reverse('zadmin.validation')

        self.version_one = Version.objects.create(addon=self.addon)
        self.version_two = Version.objects.create(addon=self.addon)

    def test_no_notify_link(self):
        self.create_result(self.job, self.create_file(), **{})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(len(doc('table tr td a.notify')), 0)

    def test_notify_link(self):
        self.create_result(self.job, self.create_file(), **{'errors': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a.notify').text(), 'Notify')

    def test_notify_url(self):
        self.create_result(self.job, self.create_file(), **{'errors': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        eq_(doc('table tr td a.notify').attr('data-job-url'), self.update_url)

    def test_notify_anonymous(self):
        self.client.logout()
        r = self.client.post(self.update_url)
        eq_(r.status_code, 302)

    def test_notify_log(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        eq_(ActivityLog.objects.for_addons(self.addon).count(), 0)
        self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        upd = amo.LOG.BULK_VALIDATION_EMAILED.id
        logs = ActivityLog.objects.for_addons(self.addon).filter(action=upd)
        eq_(logs.count(), 1)
        eq_(logs[0].user, self.creator)

    def test_notify_mail(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url, {'text': '..',
                                               'subject': '{{ ADDON_NAME }}'
                                               })
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].body, '..')
        eq_(mail.outbox[0].subject, self.addon.name)
        eq_(mail.outbox[0].to, [u'del@icio.us'])

    def test_result_links(self):
        result = self.create_result(self.job, self.create_file(self.version),
                                    **{'errors': 1})
        r = self.client.post(self.update_url, {'text': '{{ RESULT_LINKS }}',
                                               'subject': '...'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 1)
        res = reverse('devhub.validation_result',
                      args=(self.addon.slug, result.pk))
        email = mail.outbox[0].body
        assert res in email, ('Unexpected message: %s' % email)

    def test_notify_mail_partial(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        self.create_result(self.job, self.create_file(self.version))
        r = self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 1)

    def test_notify_mail_multiple(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 2)

    def test_notify_mail_preview(self):
        for i in range(2):
            self.create_result(self.job, self.create_file(self.version),
                               **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': 'the message', 'subject': 'the subject',
                              'preview_only': 'on'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 0)
        rs = self.job.get_failure_preview_emails()
        eq_([e.subject for e in rs], ['the subject', 'the subject'])

    def test_notify_rendering(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': '{{ ADDON_NAME }}{{ COMPAT_LINK }}',
                              'subject': '{{ ADDON_NAME }} blah'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 1)
        url = reverse('devhub.versions.edit', args=[self.addon.pk,
                                                    self.version.pk])
        assert str(self.addon.name) in mail.outbox[0].body
        assert url in mail.outbox[0].body
        assert str(self.addon.name) in mail.outbox[0].subject

    def test_notify_unicode(self):
        self.addon.name = u'འབྲུག་ཡུལ།'
        self.addon.save()
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': '{{ ADDON_NAME }}',
                              'subject': '{{ ADDON_NAME }} blah'})
        eq_(r.status_code, 302)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].body, self.addon.name)

    def test_notify_template(self):
        for text, res in (['some sample text', True],
                          ['{{ fooo }}{% if %}', False]):
            eq_(NotifyForm({'text': text, 'subject': '...'}).is_valid(), res)

    def test_notify_syntax(self):
        for text, res in (['some sample text', True],
                          ['{{ fooo }}{% if %}', False]):
            r = self.client.post(self.syntax_url, {'text': text,
                                                   'subject': '..'})
            eq_(r.status_code, 200)
            eq_(json.loads(r.content)['valid'], res)


class TestBulkValidationTask(BulkValidationTest):

    def start_validation(self, new_max='3.7a3'):
        self.new_max = self.appversion(new_max)
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
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject,
            'Behold! Validation results for Firefox %s->%s'
            % (self.curr_max.version, self.new_max.version))
        eq_(mail.outbox[0].to, ['fliggy@mozilla.com'])

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

    @mock.patch('zadmin.tasks.run_validator')
    def test_validate_all_tiers(self, run_validator):
        run_validator.return_value = json.dumps(no_op_validation)
        res = self.create_result(self.create_job(), self.create_file(), **{})
        tasks.bulk_validate_file(res.id)
        assert run_validator.called
        eq_(run_validator.call_args[1]['test_all_tiers'], True)

    @mock.patch('zadmin.tasks.run_validator')
    def test_merge_with_compat_summary(self, run_validator):
        data = {
            "errors": 1,
            "detected_type": "extension",
            "success": False,
            "warnings": 50,
            "notices": 1,
            "ending_tier": 5,
            "messages": [
            {
                "description": "A global function was called ...",
                "tier": 3,
                "message": "Global called in dangerous manner",
                "uid": "de93a48831454e0b9d965642f6d6bf8f",
                "compatibility_type": None,
                "for_appversions": None,
                "type": "warning"
            },
            {
                "description": ("...no longer indicate the language "
                                "of Firefox's UI..."),
                "tier": 5,
                "message": "navigator.language may not behave as expected",
                "uid": "f44c1930887c4d9e8bd2403d4fe0253a",
                "compatibility_type": "error",
                "for_appversions": {
                    "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["4.2a1pre",
                                                               "5.0a2",
                                                               "6.0a1"]
                },
                "type": "warning"
            }],
            "compatibility_summary": {
                "notices": 1,
                "errors": 6,
                "warnings": 0
            },
            "metadata": {
                "version": "1.0",
                "name": "FastestFox",
                "id": "<id>"
            }
        }
        run_validator.return_value = json.dumps(data)
        res = self.create_result(self.create_job(), self.create_file(), **{})
        tasks.bulk_validate_file(res.id)
        assert run_validator.called
        res = ValidationResult.objects.get(pk=res.pk)
        eq_(res.errors,
            data['errors'] + data['compatibility_summary']['errors'])
        eq_(res.warnings,
            data['warnings'] + data['compatibility_summary']['warnings'])
        eq_(res.notices,
            data['notices'] + data['compatibility_summary']['notices'])

    @mock.patch('validator.validate.validate')
    def test_max_version_override(self, validate):
        validate.return_value = json.dumps(no_op_validation)
        self.start_validation(new_max='3.7a4')
        assert validate.called
        eq_(validate.call_args[1]['overrides'],
            {"targetapp_maxVersion": {amo.FIREFOX.guid: '3.7a4'}})

    def create_version(self, addon, statuses):
        version = Version.objects.create(addon=addon)
        for status in statuses:
            file = File.objects.create(status=status, version=version)
        return version

    def test_getting_status(self):
        version = self.create_version(self.addon, [amo.STATUS_PUBLIC,
                                                   amo.STATUS_NOMINATED])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(version.files.all()[0].pk, ids[0])

    def test_getting_status_lite_and_nominated(self):
        version = self.create_version(self.addon,
                                      [amo.STATUS_PUBLIC,
                                       amo.STATUS_LITE_AND_NOMINATED])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(version.files.all()[0].pk, ids[0])

    def test_getting_latest_public(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon, [amo.STATUS_NULL])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(old_version.files.all()[0].pk, ids[0])

    def test_getting_latest_public_order(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PURGATORY])
        new_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(new_version.files.all()[0].pk, ids[0])

    def test_getting_w_pending(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon, [amo.STATUS_PENDING])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 2)
        eq_([old_version.files.all()[0].pk, new_version.files.all()[0].pk],
            ids)

    def test_multiple_files(self):
        version = self.create_version(self.addon, [amo.STATUS_LISTED,
                                                   amo.STATUS_LISTED,
                                                   amo.STATUS_LISTED])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 3)

    def test_multiple_public(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(new_version.files.all()[0].pk, ids[0])

    def test_multiple_addons(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        version = self.create_version(addon, [amo.STATUS_PURGATORY])
        ids = find_files(amo.FIREFOX, self.curr_max)
        eq_(len(ids), 1)
        eq_(self.version.files.all()[0].pk, ids[0])

def test_settings():
    # Are you there, settings page?
    response = test.Client().get(reverse('zadmin.settings'), follow=True)
    eq_(response.status_code, 200)


class TestEmailPreview(test_utils.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        addon = Addon.objects.get(pk=3615)
        self.topic = EmailPreviewTopic(addon)

    def test_csv(self):
        self.topic.send_mail('the subject', u'Hello Ivan Krsti\u0107',
                             from_email='admin@mozilla.org',
                             recipient_list=['funnyguy@mozilla.org'])
        r = self.client.get(reverse('zadmin.email_preview_csv',
                            args=[self.topic.topic]))
        eq_(r.status_code, 200)
        rdr = csv.reader(StringIO(r.content))
        eq_(rdr.next(), ['from_email', 'recipient_list', 'subject', 'body'])
        eq_(rdr.next(), ['admin@mozilla.org', 'funnyguy@mozilla.org',
                         'the subject', 'Hello Ivan Krsti\xc4\x87'])
