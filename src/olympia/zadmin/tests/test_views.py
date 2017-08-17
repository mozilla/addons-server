# -*- coding: utf-8 -*-
import csv
import os
import json
from cStringIO import StringIO
from datetime import datetime

from django.conf import settings
from django.core import mail
from django.core.cache import cache

import mock
from pyquery import PyQuery as pq
from lxml.html import HTMLParser, fromstring

import olympia
from olympia import amo
from olympia.amo.tests import (
    TestCase, formset, initial, file_factory, user_factory, version_factory)
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, CompatOverride, CompatOverrideRange
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import FeaturedCollection, MonthlyPick
from olympia.compat import FIREFOX_COMPAT
from olympia.compat.tests import TestCompatibilityReportCronMixin
from olympia.constants.base import VALIDATOR_SKELETON_RESULTS
from olympia.files.models import File, FileUpload
from olympia.users.models import UserProfile
from olympia.users.utils import get_task_user
from olympia.versions.models import ApplicationsVersions, Version
from olympia.zadmin import forms, tasks
from olympia.zadmin.forms import DevMailerForm
from olympia.zadmin.models import (
    EmailPreviewTopic, ValidationJob, ValidationResult,
    ValidationResultAffectedAddon, ValidationResultMessage)
from olympia.zadmin.tasks import updated_versions
from olympia.zadmin.views import find_files


SHORT_LIVED_CACHE_PARAMS = settings.CACHES.copy()
SHORT_LIVED_CACHE_PARAMS['default']['TIMEOUT'] = 2


ZADMIN_TEST_FILES = os.path.join(
    os.path.dirname(olympia.__file__),
    'zadmin', 'tests', 'resources')


class TestHomeAndIndex(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestHomeAndIndex, self).setUp()
        self.client.login(email='admin@mozilla.com')

    def test_get_home(self):
        url = reverse('zadmin.home')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert response.context['user'].username == 'admin'
        assert response.context['user'].email == 'admin@mozilla.com'

    def test_get_index(self):
        # Add fake log that would be shown in the index page.
        user = UserProfile.objects.get(email='admin@mozilla.com')
        ActivityLog.create(
            amo.LOG.GROUP_USER_ADDED, user.groups.latest('pk'), user,
            user=user)
        url = reverse('zadmin.index')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert response.context['user'].username == 'admin'
        assert response.context['user'].email == 'admin@mozilla.com'

    def test_django_index(self):
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        self.client.logout()
        response = self.client.get(url)
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email='staffperson@m.c')
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

    def test_django_admin_logout(self):
        url = reverse('admin:logout')
        response = self.client.get(url)
        assert response.status_code == 200


class TestStaffAdmin(TestCase):
    def test_index(self):
        url = reverse('staffadmin:index')
        response = self.client.get(url)
        self.assert3xx(response, '/admin/staff-models/login/?'
                                 'next=/en-US/admin/staff-models/')

        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.grant_permission(user, 'Addons:Edit')
        self.client.login(email='staffperson@m.c')
        response = self.client.get(url)
        assert response.status_code == 200
        assert 'Replacement addons' in response.content

    def test_model_page(self):
        url = reverse('staffadmin:addons_replacementaddon_changelist')
        user = user_factory(username='staffperson', email='staffperson@m.c')
        redirect_url_403 = ('/admin/staff-models/login/?next=/en-US/admin/'
                            'staff-models/addons/replacementaddon/')

        # Not logged in.
        response = self.client.get(url)
        self.assert3xx(response, redirect_url_403)

        # Logged in but not auth'd.
        self.client.login(email='staffperson@m.c')
        response = self.client.get(url)
        self.assert3xx(response, redirect_url_403)

        # Only succeeds with correct permission.
        self.grant_permission(user, 'Addons:Edit')
        response = self.client.get(url)
        assert response.status_code == 200
        assert 'Select replacement addon to change' in response.content


class TestSiteEvents(TestCase):
    fixtures = ['base/users', 'zadmin/tests/siteevents']

    def setUp(self):
        super(TestSiteEvents, self).setUp()
        self.client.login(email='admin@mozilla.com')

    def test_get(self):
        url = reverse('zadmin.site_events')
        response = self.client.get(url)
        assert response.status_code == 200
        events = response.context['events']
        assert len(events) == 1

    def test_add(self):
        url = reverse('zadmin.site_events')
        new_event = {
            'event_type': 2,
            'start': '2012-01-01',
            'description': 'foo',
        }
        response = self.client.post(url, new_event, follow=True)
        assert response.status_code == 200
        events = response.context['events']
        assert len(events) == 2

    def test_edit(self):
        url = reverse('zadmin.site_events', args=[1])
        modified_event = {
            'event_type': 2,
            'start': '2012-01-01',
            'description': 'bar',
        }
        response = self.client.post(url, modified_event, follow=True)
        assert response.status_code == 200
        events = response.context['events']
        assert events[0].description == 'bar'

    def test_delete(self):
        url = reverse('zadmin.site_events.delete', args=[1])
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        events = response.context['events']
        assert len(events) == 0


class BulkValidationTest(TestCase):
    fixtures = ['base/addon_3615', 'base/appversion', 'base/users']

    def setUp(self):
        super(BulkValidationTest, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.addon = Addon.objects.get(pk=3615)
        self.creator = UserProfile.objects.get(username='editor')
        self.version = self.addon.find_latest_public_listed_version()
        ApplicationsVersions.objects.filter(
            application=amo.FIREFOX.id, version=self.version).update(
            max=AppVersion.objects.get(application=1, version='3.7a1pre'))
        self.application_version = self.version.apps.all()[0]
        self.application = self.application_version.application
        self.min = self.application_version.min
        self.max = self.application_version.max
        self.curr_max = self.appversion('3.7a1pre')
        self.counter = 0

        self.old_task_user = settings.TASK_USER_ID
        settings.TASK_USER_ID = self.creator.id

    def tearDown(self):
        settings.TASK_USER_ID = self.old_task_user
        super(BulkValidationTest, self).tearDown()

    def appversion(self, version, application=amo.FIREFOX.id):
        return AppVersion.objects.get(application=application,
                                      version=version)

    def create_job(self, **kwargs):
        kw = dict(application=amo.FIREFOX.id,
                  curr_max_version=kwargs.pop('current', self.curr_max),
                  target_version=kwargs.pop('target',
                                            self.appversion('3.7a3')),
                  creator=self.creator)
        kw.update(kwargs)

        return ValidationJob.objects.create(**kw)

    def create_file(self, version=None, platform=amo.PLATFORM_ALL.id):
        if not version:
            version = self.version
        return File.objects.create(version=version,
                                   filename='file-%s' % self.counter,
                                   platform=platform,
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

    def start_validation(self, new_max='3.7a3'):
        self.new_max = self.appversion(new_max)
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': self.new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        assert r.status_code == 200


class TestBulkValidation(BulkValidationTest):

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_start(self, bulk_validate_file):
        new_max = self.appversion('3.7a3')
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assert3xx(r, reverse('zadmin.validation'))
        job = ValidationJob.objects.get()
        assert job.application == amo.FIREFOX.id
        assert job.curr_max_version.version == self.curr_max.version
        assert job.target_version.version == new_max.version
        assert job.finish_email == 'fliggy@mozilla.com'
        assert job.completed is None
        assert job.result_set.all().count() == len(self.version.all_files)
        assert bulk_validate_file.delay.called

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_ignore_unlisted_versions(self, bulk_validate_file):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        new_max = self.appversion('3.7a3')
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': new_max.id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assert3xx(r, reverse('zadmin.validation'))
        job = ValidationJob.objects.get()
        assert job.application == amo.FIREFOX.id
        assert job.curr_max_version.version == self.curr_max.version
        assert job.target_version.version == new_max.version
        assert job.finish_email == 'fliggy@mozilla.com'
        assert job.completed is None
        assert job.result_set.all().count() == len(self.version.all_files)
        assert bulk_validate_file.delay.called

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_ignore_user_disabled_addons(self, bulk_validate_file):
        self.addon.update(disabled_by_user=True)
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': self.appversion('3.7a3').id,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assert3xx(r, reverse('zadmin.validation'))
        assert not bulk_validate_file.delay.called

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_ignore_non_public_addons(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        for status in (amo.STATUS_DISABLED, amo.STATUS_NULL,
                       amo.STATUS_DELETED):
            self.addon.update(status=status)
            r = self.client.post(reverse('zadmin.start_validation'),
                                 {'application': amo.FIREFOX.id,
                                  'curr_max_version': self.curr_max.id,
                                  'target_version': target_ver,
                                  'finish_email': 'fliggy@mozilla.com'},
                                 follow=True)
            self.assertNoFormErrors(r)
            self.assert3xx(r, reverse('zadmin.validation'))
            assert not bulk_validate_file.delay.called, (
                'Addon with status %s should be ignored' % status)

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_ignore_lang_packs(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        self.addon.update(type=amo.ADDON_LPAPP)
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': target_ver,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assert3xx(r, reverse('zadmin.validation'))
        assert not bulk_validate_file.delay.called, (
            'Lang pack addons should be ignored')

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_ignore_themes(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        self.addon.update(type=amo.ADDON_THEME)
        self.client.post(reverse('zadmin.start_validation'),
                         {'application': amo.FIREFOX.id,
                          'curr_max_version': self.curr_max.id,
                          'target_version': target_ver,
                          'finish_email': 'fliggy@mozilla.com'})
        assert not bulk_validate_file.delay.called, (
            'Theme addons should be ignored')

    @mock.patch('olympia.zadmin.tasks.bulk_validate_file')
    def test_validate_all_non_disabled_addons(self, bulk_validate_file):
        target_ver = self.appversion('3.7a3').id
        bulk_validate_file.delay.called = False
        self.addon.update(status=amo.STATUS_PUBLIC)
        r = self.client.post(reverse('zadmin.start_validation'),
                             {'application': amo.FIREFOX.id,
                              'curr_max_version': self.curr_max.id,
                              'target_version': target_ver,
                              'finish_email': 'fliggy@mozilla.com'},
                             follow=True)
        self.assertNoFormErrors(r)
        self.assert3xx(r, reverse('zadmin.validation'))
        assert bulk_validate_file.delay.called, (
            'Addon with status %s should be validated' % self.addon.status)

    def test_grid(self):
        job = self.create_job()
        for res in (dict(errors=0), dict(errors=1)):
            self.create_result(job, self.create_file(), **res)

        r = self.client.get(reverse('zadmin.validation'))
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('table tr td').eq(0).text() == str(job.pk)  # ID
        assert doc('table tr td').eq(3).text() == 'Firefox'  # Application
        assert doc('table tr td').eq(4).text() == self.curr_max.version
        assert doc('table tr td').eq(5).text() == '3.7a3'
        assert doc('table tr td').eq(6).text() == '2'  # tested
        assert doc('table tr td').eq(7).text() == '1'  # failing
        assert doc('table tr td').eq(8).text()[0] == '1'  # passing
        assert doc('table tr td').eq(9).text() == '0'  # exceptions

    def test_application_versions_json(self):
        r = self.client.post(reverse('zadmin.application_versions_json'),
                             {'application': amo.FIREFOX.id})
        assert r.status_code == 200
        data = json.loads(r.content)
        empty = True
        for id, ver in data['choices']:
            empty = False
            assert AppVersion.objects.get(pk=id).version == ver
        assert not empty, "Unexpected: %r" % data

    def test_job_status(self):
        job = self.create_job()

        def get_data():
            self.create_result(job, self.create_file(), **{})
            r = self.client.post(reverse('zadmin.job_status'),
                                 {'job_ids': json.dumps([job.pk])})
            assert r.status_code == 200
            data = json.loads(r.content)[str(job.pk)]
            return data

        data = get_data()
        assert data['completed'] == 1
        assert data['total'] == 1
        assert data['percent_complete'] == '100'
        assert data['job_id'] == job.pk
        assert data['completed_timestamp'] == ''
        job.update(completed=datetime.now())
        data = get_data()
        assert data['completed_timestamp'] != '', (
            'Unexpected: %s' % data['completed_timestamp'])

    def test_bulk_validation_summary(self):
        new_max = self.appversion('3.7a3')
        response = self.client.post(
            reverse('zadmin.start_validation'),
            {
                'application': amo.FIREFOX.id,
                'curr_max_version': self.curr_max.id,
                'target_version': new_max.id,
                'finish_email': u'fliggy@mozilla.com'
            },
            follow=True)

        self.assert3xx(response, reverse('zadmin.validation'))

        job = ValidationJob.objects.get()
        result = job.result_set.get()

        compat_summary_path = os.path.join(
            ZADMIN_TEST_FILES, 'compatibility_validation.json')

        with open(compat_summary_path) as fobj:
            validation = fobj.read()

        result.apply_validation(validation)

        response = self.client.get(
            reverse('zadmin.validation_summary', args=(job.pk,)))

        assert response.status_code == 200

        UTF8_PARSER = HTMLParser(encoding='utf-8')
        doc = pq(fromstring(response.content, parser=UTF8_PARSER))

        msgid = u'testcases_regex.generic.餐飲'
        assert doc('table tr').eq(3).find('td').eq(0).text() == msgid
        assert doc('table tr').eq(3).find('td').eq(1).text() == 'compat error'

        assert (
            doc('table tr').eq(1).find('td').eq(0).text() ==
            '19ab4e645c1dc715977d707481f89292654c19cd558db4e0b9c97f2a438c2282')
        assert (
            doc('table tr').eq(2).find('td').eq(0).text() ==
            '5a997b84c5f318d9a0189d2bf0d616ffb02dbfbaf70fb5545c651bee0e1b9c1a')

    def test_bulk_validation_summary_detail(self):
        self.addon.name = '美味的食物'
        self.addon.save()

        new_max = self.appversion('3.7a3')
        response = self.client.post(
            reverse('zadmin.start_validation'),
            {
                'application': amo.FIREFOX.id,
                'curr_max_version': self.curr_max.id,
                'target_version': new_max.id,
                'finish_email': 'fliggy@mozilla.com'
            },
            follow=True)

        self.assert3xx(response, reverse('zadmin.validation'))

        job = ValidationJob.objects.get()
        result = job.result_set.get()

        compat_summary_path = os.path.join(
            ZADMIN_TEST_FILES, 'compatibility_validation.json')

        with open(compat_summary_path) as fobj:
            validation = fobj.read()

        result.apply_validation(validation)

        message = ValidationResultMessage.objects.first()

        url = reverse(
            'zadmin.validation_summary_detail',
            args=(message.validation_job.pk, message.pk,))
        response = self.client.get(url)

        assert response.status_code == 200

        UTF8_PARSER = HTMLParser(encoding='utf-8')
        doc = pq(fromstring(response.content, parser=UTF8_PARSER))
        assert message.message_id in doc('div#message_details').text()
        assert message.message in doc('div#message_details').text()
        assert doc('table tr td').eq(0).text() == u'美味的食物'
        assert '3615/validation-resul' in doc('table tr td').eq(1).html()

    def test_bulk_validation_summary_multiple_files(self):
        version = self.addon.versions.all()[0]
        version.files.add(file_factory(version=version))

        new_max = self.appversion('3.7a3')
        response = self.client.post(
            reverse('zadmin.start_validation'),
            {
                'application': amo.FIREFOX.id,
                'curr_max_version': self.curr_max.id,
                'target_version': new_max.id,
                'finish_email': u'fliggy@mozilla.com'
            },
            follow=True)

        self.assert3xx(response, reverse('zadmin.validation'))

        job = ValidationJob.objects.get()

        # Apply validation for all result sets (two because we added a
        # new version). This should not lead to duplicate add-ons
        # being added to the list
        for result in job.result_set.all():
            compat_summary_path = os.path.join(
                ZADMIN_TEST_FILES, 'compatibility_validation.json')

            with open(compat_summary_path) as fobj:
                validation = fobj.read()

            result.apply_validation(validation)

        message = ValidationResultMessage.objects.first()

        url = reverse(
            'zadmin.validation_summary_detail',
            args=(message.validation_job.pk, message.pk,))
        response = self.client.get(url)

        assert response.status_code == 200

        UTF8_PARSER = HTMLParser(encoding='utf-8')
        doc = pq(fromstring(response.content, parser=UTF8_PARSER))
        assert doc('table').html().count('Delicious Bookmarks') == 1


class TestBulkUpdate(BulkValidationTest):

    def setUp(self):
        super(TestBulkUpdate, self).setUp()

        self.job = self.create_job(completed=datetime.now())
        self.update_url = reverse('zadmin.notify', args=[self.job.pk])
        self.list_url = reverse('zadmin.validation')
        self.data = {'text': '{{ APPLICATION }} {{ VERSION }}',
                     'subject': '..'}

        self.version_one = Version.objects.create(addon=self.addon)
        self.version_two = Version.objects.create(addon=self.addon)

        appver = AppVersion.objects.get(application=1, version='3.7a1pre')
        for v in self.version_one, self.version_two:
            ApplicationsVersions.objects.create(
                application=amo.FIREFOX.id, version=v,
                min=appver, max=appver)

    def test_no_update_link(self):
        self.create_result(self.job, self.create_file(), **{})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('table tr td a.set-max-version').text() == (
            'Notify and set max versions')

    def test_update_link(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('table tr td a.set-max-version').text() == (
            'Notify and set max versions')

    def test_update_url(self):
        self.create_result(self.job, self.create_file(), **{'valid': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('table tr td a.set-max-version').attr('data-job-url') == (
            self.update_url)

    def test_update_anonymous(self):
        self.client.logout()
        r = self.client.post(self.update_url)
        assert r.status_code == 302

    def test_version_pks(self):
        for version in [self.version_one, self.version_two]:
            for x in range(0, 3):
                self.create_result(self.job, self.create_file(version))

        assert sorted(updated_versions(self.job)) == (
            [self.version_one.pk, self.version_two.pk])

    def test_update_passing_only(self):
        self.create_result(self.job, self.create_file(self.version_one))
        self.create_result(self.job, self.create_file(self.version_two),
                           errors=1)

        assert sorted(updated_versions(self.job)) == (
            [self.version_one.pk])

    def test_update_pks(self):
        self.create_result(self.job, self.create_file(self.version))
        r = self.client.post(self.update_url, self.data)
        assert r.status_code == 302
        assert self.version.apps.all()[0].max == self.job.target_version

    def test_update_unclean_pks(self):
        self.create_result(self.job, self.create_file(self.version))
        self.create_result(self.job, self.create_file(self.version),
                           errors=1)
        r = self.client.post(self.update_url, self.data)
        assert r.status_code == 302
        assert self.version.apps.all()[0].max == self.job.curr_max_version

    def test_update_pks_logs(self):
        self.create_result(self.job, self.create_file(self.version))
        assert ActivityLog.objects.for_addons(self.addon).count() == 0
        self.client.post(self.update_url, self.data)
        upd = amo.LOG.MAX_APPVERSION_UPDATED.id
        logs = ActivityLog.objects.for_addons(self.addon).filter(action=upd)
        assert logs.count() == 1
        assert logs[0].user == get_task_user()

    def test_update_wrong_version(self):
        self.create_result(self.job, self.create_file(self.version))
        av = self.version.apps.all()[0]
        av.max = self.appversion('3.6')
        av.save()
        self.client.post(self.update_url, self.data)
        assert self.version.apps.all()[0].max == self.appversion('3.6')

    def test_update_all_within_range(self):
        self.create_result(self.job, self.create_file(self.version))
        # Create an appversion in between current and target.
        av = self.version.apps.all()[0]
        av.max = self.appversion('3.7a2')
        av.save()
        self.client.post(self.update_url, self.data)
        assert self.version.apps.all()[0].max == self.appversion('3.7a3')

    def test_version_comparison(self):
        # regression test for bug 691984
        job = self.create_job(completed=datetime.now(),
                              current=self.appversion('3.0.9'),
                              target=self.appversion('3.5'))
        # .* was not sorting right
        self.version.apps.all().update(max=self.appversion('3.0.*'))
        self.create_result(job, self.create_file(self.version))
        self.client.post(reverse('zadmin.notify', args=[job.pk]),
                         self.data)
        assert self.version.apps.all()[0].max == self.appversion('3.5')

    def test_update_different_app(self):
        self.create_result(self.job, self.create_file(self.version))
        target = self.version.apps.all()[0]
        target.application = amo.FIREFOX.id
        target.save()
        assert self.version.apps.all()[0].max == self.curr_max

    def test_update_twice(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        assert self.version.apps.all()[0].max == self.job.target_version
        now = self.version.modified
        self.client.post(self.update_url, self.data)
        assert self.version.modified == now

    def test_update_notify(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        assert len(mail.outbox) == 1

    def test_update_subject(self):
        data = self.data.copy()
        data['subject'] = '{{ PASSING_ADDONS.0.name }}'
        f = self.create_file(self.version)
        self.create_result(self.job, f)
        self.client.post(self.update_url, data)
        assert mail.outbox[0].subject == (
            '%s' % self.addon.name)

    @mock.patch('olympia.zadmin.tasks.log')
    def test_bulk_email_logs_stats(self, log):
        log.info = mock.Mock()
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        assert log.info.call_args_list[-8][0][0] == (
            '[1@None] bulk update stats for job %s: '
            '{bumped: 1, is_dry_run: 0, processed: 1}'
            % self.job.pk)
        assert log.info.call_args_list[-2][0][0] == (
            '[1@None] bulk email stats for job %s: '
            '{author_emailed: 1, is_dry_run: 0, processed: 1}'
            % self.job.pk)

    def test_application_version(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url, self.data)
        assert mail.outbox[0].body == 'Firefox 3.7a3'

    def test_multiple_result_links(self):
        # Creates validation results for two files of the same addon:
        results = [
            self.create_result(self.job, self.create_file(self.version)),
            self.create_result(self.job, self.create_file(self.version))]
        self.client.post(self.update_url,
                         {'text': '{{ PASSING_ADDONS.0.links }}',
                          'subject': '..'})
        body = mail.outbox[0].body
        assert all((reverse('devhub.bulk_compat_result',
                            args=(self.addon.slug, result.pk))
                    in body)
                   for result in results)

    def test_notify_mail_preview(self):
        self.create_result(self.job, self.create_file(self.version))
        self.client.post(self.update_url,
                         {'text': 'the message', 'subject': 'the subject',
                          'preview_only': 'on'})
        assert len(mail.outbox) == 0
        rs = self.job.get_notify_preview_emails()
        assert [e.subject for e in rs] == ['the subject']
        # version should not be bumped since it's in preview mode:
        assert self.version.apps.all()[0].max == self.max
        upd = amo.LOG.MAX_APPVERSION_UPDATED.id
        logs = ActivityLog.objects.for_addons(self.addon).filter(action=upd)
        assert logs.count() == 0


class TestBulkNotify(BulkValidationTest):

    def setUp(self):
        super(TestBulkNotify, self).setUp()

        self.job = self.create_job(completed=datetime.now())
        self.update_url = reverse('zadmin.notify', args=[self.job.pk])
        self.syntax_url = reverse('zadmin.notify.syntax')
        self.list_url = reverse('zadmin.validation')

        self.version_one = Version.objects.create(addon=self.addon)
        self.version_two = Version.objects.create(addon=self.addon)

    def test_no_notify_link(self):
        self.create_result(self.job, self.create_file(), **{})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert len(doc('table tr td a.notify')) == 0

    def test_notify_link(self):
        self.create_result(self.job, self.create_file(), **{'errors': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('table tr td a.set-max-version').text() == (
            'Notify and set max versions')

    def test_notify_url(self):
        self.create_result(self.job, self.create_file(), **{'errors': 1})
        r = self.client.get(self.list_url)
        doc = pq(r.content)
        assert doc('table tr td a.set-max-version').attr('data-job-url') == (
            self.update_url)

    def test_notify_anonymous(self):
        self.client.logout()
        r = self.client.post(self.update_url)
        assert r.status_code == 302

    def test_notify_log(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        assert ActivityLog.objects.for_addons(self.addon).count() == 0
        self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        upd = amo.LOG.BULK_VALIDATION_USER_EMAILED.id
        logs = (ActivityLog.objects.for_user(self.creator)
                           .filter(action=upd))
        assert logs.count() == 1
        assert logs[0].user == self.creator

    def test_compat_bump_log(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 0})
        assert ActivityLog.objects.for_addons(self.addon).count() == 0
        self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        upd = amo.LOG.MAX_APPVERSION_UPDATED.id
        logs = ActivityLog.objects.for_addons(self.addon).filter(action=upd)
        assert logs.count() == 1
        assert logs[0].user == self.creator

    def test_notify_mail(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': '..',
                              'subject': '{{ FAILING_ADDONS.0.name }}'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        assert mail.outbox[0].body == '..'
        assert mail.outbox[0].subject == self.addon.name
        assert mail.outbox[0].to == [u'del@icio.us']

    def test_result_links(self):
        result = self.create_result(self.job, self.create_file(self.version),
                                    **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': '{{ FAILING_ADDONS.0.links }}',
                              'subject': '...'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        res = reverse('devhub.bulk_compat_result',
                      args=(self.addon.slug, result.pk))
        email = mail.outbox[0].body
        assert res in email, ('Unexpected message: %s' % email)

    def test_notify_mail_partial(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        self.create_result(self.job, self.create_file(self.version))
        r = self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1

    def test_notify_mail_multiple(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url, {'text': '..', 'subject': '..'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1

    def test_notify_mail_preview(self):
        for i in range(2):
            self.create_result(self.job, self.create_file(self.version),
                               **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': 'the message', 'subject': 'the subject',
                              'preview_only': 'on'})
        assert r.status_code == 302
        assert len(mail.outbox) == 0
        rs = self.job.get_notify_preview_emails()
        assert [e.subject for e in rs] == ['the subject']

    def test_notify_rendering(self):
        self.create_result(self.job, self.create_file(self.version),
                           **{'errors': 1})
        r = self.client.post(self.update_url,
                             {'text': '{{ FAILING_ADDONS.0.name }}'
                                      '{{ FAILING_ADDONS.0.compat_link }}',
                              'subject': '{{ FAILING_ADDONS.0.name }} blah'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1
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
                             {'text': '{{ FAILING_ADDONS.0.name }}',
                              'subject': '{{ FAILING_ADDONS.0.name }} blah'})
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        assert mail.outbox[0].body == self.addon.name

    def test_notify_template(self):
        for text, res in (['some sample text', True],
                          ['{{ FAILING_ADDONS.0.name }}{% if %}', False]):
            assert forms.NotifyForm(
                {'text': text, 'subject': '...'}).is_valid() == res

    def test_notify_syntax(self):
        for text, res in (['some sample text', True],
                          ['{{ FAILING_ADDONS.0.name }}{% if %}', False]):
            r = self.client.post(self.syntax_url, {'text': text,
                                                   'subject': '..'})
            assert r.status_code == 200
            assert json.loads(r.content)['valid'] == res


class TestBulkValidationTask(BulkValidationTest):

    def test_validate(self):
        self.start_validation()
        res = ValidationResult.objects.get()
        self.assertCloseToNow(res.completed)
        assert not res.task_error
        validation = json.loads(res.validation)
        assert res.errors == 1
        assert validation['messages'][0]['id'] == ['main', 'prepare_package',
                                                   'not_found']
        assert res.valid is False
        assert res.warnings == 0, [mess['message']
                                   for mess in validation['messages']]
        assert res.notices == 0
        assert validation['errors'] == 1
        self.assertCloseToNow(res.validation_job.completed)
        assert res.validation_job.stats['total'] == 1
        assert res.validation_job.stats['completed'] == 1
        assert res.validation_job.stats['passing'] == 0
        assert res.validation_job.stats['failing'] == 1
        assert res.validation_job.stats['errors'] == 0
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == (
            'Behold! Validation results for Firefox %s->%s'
            % (self.curr_max.version, self.new_max.version))
        assert mail.outbox[0].to == ['fliggy@mozilla.com']

    @mock.patch('validator.validate.validate')
    def test_validator_bulk_compat_flag(self, validate):
        try:
            self.start_validation()
        except Exception:
            # We only care about the call to `validate()`, not the result.
            pass
        assert validate.call_args[1].get('compat_test')

    @mock.patch('olympia.zadmin.tasks.run_validator')
    def test_task_error(self, run_validator):
        run_validator.side_effect = RuntimeError('validation error')
        try:
            self.start_validation()
        except:
            # the real test is how it's handled, below...
            pass
        res = ValidationResult.objects.get()
        err = res.task_error.strip()
        assert err.endswith('RuntimeError: validation error'), (
            'Unexpected: %s' % err)
        self.assertCloseToNow(res.completed)
        assert res.validation_job.stats['total'] == 1
        assert res.validation_job.stats['errors'] == 1
        assert res.validation_job.stats['passing'] == 0
        assert res.validation_job.stats['failing'] == 0

    @mock.patch('olympia.zadmin.tasks.run_validator')
    def test_validate_for_appversions(self, run_validator):
        data = {
            "errors": 1,
            "warnings": 50,
            "notices": 1,
            "messages": [],
            "compatibility_summary": {
                "errors": 0,
                "warnings": 0,
                "notices": 0
            },
            "metadata": {}
        }
        run_validator.return_value = json.dumps(data)
        self.start_validation()
        assert run_validator.called
        assert run_validator.call_args[1]['for_appversions'] == (
            {amo.FIREFOX.guid: [self.new_max.version]})

    @mock.patch('olympia.zadmin.tasks.run_validator')
    def test_validate_all_tiers(self, run_validator):
        run_validator.return_value = json.dumps(VALIDATOR_SKELETON_RESULTS)
        res = self.create_result(self.create_job(), self.create_file(), **{})
        tasks.bulk_validate_file(res.id)
        assert run_validator.called
        assert run_validator.call_args[1]['test_all_tiers']

    @mock.patch('olympia.zadmin.tasks.run_validator')
    def test_merge_with_compat_summary(self, run_validator):
        data = {
            "errors": 1,
            "detected_type": "extension",
            "success": False,
            "warnings": 50,
            "notices": 1,
            "ending_tier": 5,
            "messages": [
                {"description": "A global function was called ...",
                 "tier": 3,
                 "message": "Global called in dangerous manner",
                 "uid": "de93a48831454e0b9d965642f6d6bf8f",
                 "id": [],
                 "compatibility_type": None,
                 "for_appversions": None,
                 "type": "warning"},
                {"description": ("...no longer indicate the language "
                                 "of Firefox's UI..."),
                 "tier": 5,
                 "message": "navigator.language may not behave as expected",
                 "uid": "f44c1930887c4d9e8bd2403d4fe0253a",
                 "id": [],
                 "compatibility_type": "error",
                 "for_appversions": {
                     "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}": ["4.2a1pre",
                                                                "5.0a2",
                                                                "6.0a1"]},
                 "type": "warning"}],
            "compatibility_summary": {
                "notices": 1,
                "errors": 6,
                "warnings": 0},
            "metadata": {
                "version": "1.0",
                "name": "FastestFox",
                "id": "<id>"}}
        run_validator.return_value = json.dumps(data)
        res = self.create_result(self.create_job(), self.create_file(), **{})
        tasks.bulk_validate_file(res.id)
        assert run_validator.called
        res = ValidationResult.objects.get(pk=res.pk)
        assert res.errors == (
            data['errors'] + data['compatibility_summary']['errors'])
        assert res.warnings == (
            data['warnings'] + data['compatibility_summary']['warnings'])
        assert res.notices == (
            data['notices'] + data['compatibility_summary']['notices'])

    @mock.patch('validator.validate.validate')
    def test_app_version_overrides(self, validate):
        validate.return_value = json.dumps(VALIDATOR_SKELETON_RESULTS)
        self.start_validation(new_max='3.7a4')
        assert validate.called
        overrides = validate.call_args[1]['overrides']
        assert overrides['targetapp_minVersion'] == {amo.FIREFOX.guid: '3.7a4'}
        assert overrides['targetapp_maxVersion'] == {amo.FIREFOX.guid: '3.7a4'}

    def create_version(self, addon, statuses, version_str=None):
        max = self.max
        if version_str:
            max = AppVersion.objects.filter(version=version_str)[0]
        version = Version.objects.create(addon=addon)

        ApplicationsVersions.objects.create(application=self.application,
                                            min=self.min, max=max,
                                            version=version)
        for status in statuses:
            File.objects.create(status=status, version=version)
        return version

    def find_files(self, job_kwargs=None):
        if not job_kwargs:
            job_kwargs = {}
        job = self.create_job(**job_kwargs)
        find_files(job)
        return list(job.result_set.values_list('file_id', flat=True))

    def test_getting_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert len(self.find_files()) == 0

    def test_getting_deleted(self):
        self.addon.update(status=amo.STATUS_DELETED)
        assert len(self.find_files()) == 0

    def test_getting_status(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC,
                                         amo.STATUS_NOMINATED])
        ids = self.find_files()
        assert len(ids) == 2

    def test_getting_latest_public(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        self.create_version(self.addon, [amo.STATUS_NULL])
        ids = self.find_files()
        assert len(ids) == 1
        assert old_version.files.all()[0].pk == ids[0]

    def test_getting_latest_public_order(self):
        self.create_version(self.addon, [amo.STATUS_AWAITING_REVIEW])
        new_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        ids = self.find_files()
        assert len(ids) == 1
        assert new_version.files.all()[0].pk == ids[0]

    def delete_orig_version(self, fixup=True):
        # Because deleting versions resets the status...
        self.version.delete()
        # Don't really care what status this is, as long
        # as it gets past the first SQL query.
        self.addon.update(status=amo.STATUS_PUBLIC)

    def test_no_versions(self):
        self.delete_orig_version()
        assert len(self.find_files()) == 0

    def test_no_files(self):
        self.version.files.all().delete()
        self.addon.update(status=amo.STATUS_PUBLIC)
        assert len(self.find_files()) == 0

    def test_beta(self):
        self.create_version(self.addon, [amo.STATUS_BETA])
        self.delete_orig_version()
        ids = self.find_files()
        assert len(ids) == 1

    def test_w_multiple_files(self):
        self.create_version(self.addon, [amo.STATUS_BETA])
        self.create_version(self.addon, [amo.STATUS_BETA,
                                         amo.STATUS_AWAITING_REVIEW])
        self.delete_orig_version()
        ids = self.find_files()
        assert len(ids) == 3

    def test_public_partial(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon, [amo.STATUS_BETA,
                                                       amo.STATUS_DISABLED])
        ids = self.find_files()
        assert len(ids) == 2
        assert new_version.files.all()[1].pk not in ids

    def test_getting_w_unreviewed(self):
        old_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon,
                                          [amo.STATUS_AWAITING_REVIEW])
        ids = self.find_files()
        assert len(ids) == 2
        old_version_pk = old_version.files.all()[0].pk
        new_version_pk = new_version.files.all()[0].pk
        assert sorted([old_version_pk, new_version_pk]) == sorted(ids)

    def test_multiple_files(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC, amo.STATUS_PUBLIC,
                                         amo.STATUS_PUBLIC])
        ids = self.find_files()
        assert len(ids) == 3

    def test_multiple_public(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC])
        new_version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        ids = self.find_files()
        assert len(ids) == 1
        assert new_version.files.all()[0].pk == ids[0]

    def test_multiple_addons(self):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.create_version(addon, [amo.STATUS_AWAITING_REVIEW])
        ids = self.find_files()
        assert len(ids) == 1
        assert self.version.files.all()[0].pk == ids[0]

    def test_no_app(self):
        version = self.create_version(self.addon, [amo.STATUS_PUBLIC])
        self.delete_orig_version()
        version.apps.all().delete()
        ids = self.find_files()
        assert len(ids) == 0

    def test_wrong_version(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='4.0b2pre')
        self.delete_orig_version()
        ids = self.find_files()
        assert len(ids) == 0

    def test_version_slightly_newer_than_current(self):
        # addon matching current app/version but with a newer public version
        # that is within range of the target app/version.
        # See bug 658739.
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='3.7a2')
        newer = self.create_version(self.addon, [amo.STATUS_PUBLIC],
                                    version_str='3.7a3')
        kw = dict(curr_max_version=self.appversion('3.7a2'),
                  target_version=self.appversion('3.7a4'))
        ids = self.find_files(job_kwargs=kw)
        assert newer.files.all()[0].pk == ids[0]

    def test_version_compatible_with_newer_app(self):
        # addon with a newer public version that is already compatible with
        # an app/version higher than the target.
        # See bug 658739.
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='3.7a2')
        # A version that supports a newer Firefox than what we're targeting
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='3.7a4')
        kw = dict(curr_max_version=self.appversion('3.7a2'),
                  target_version=self.appversion('3.7a3'))
        ids = self.find_files(job_kwargs=kw)
        assert len(ids) == 0

    def test_version_compatible_with_target_app(self):
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='3.7a2')
        # Already has a version that supports target:
        self.create_version(self.addon, [amo.STATUS_PUBLIC],
                            version_str='3.7a3')
        kw = dict(curr_max_version=self.appversion('3.7a2'),
                  target_version=self.appversion('3.7a3'))
        ids = self.find_files(job_kwargs=kw)
        assert len(ids) == 0

    def test_version_webextension(self):
        self.version.files.update(is_webextension=True)
        assert not self.find_files()


class TestTallyValidationErrors(BulkValidationTest):

    def setUp(self):
        super(TestTallyValidationErrors, self).setUp()
        self.data = {
            "errors": 1,
            "warnings": 1,
            "notices": 0,
            "messages": [
                {"message": "message one",
                 "description": ["message one long"],
                 "id": ["path", "to", "test_one"],
                 "uid": "de93a48831454e0b9d965642f6d6bf8f",
                 "type": "error"},
                {"message": "message two",
                 "description": "message two long",
                 "id": ["path", "to", "test_two"],
                 "uid": "f44c1930887c4d9e8bd2403d4fe0253a",
                 "compatibility_type": "error",
                 "type": "warning"}],
            "metadata": {},
            "compatibility_summary": {
                "errors": 1,
                "warnings": 1,
                "notices": 0}}

    @mock.patch('olympia.zadmin.tasks.run_validator')
    def test_result_messages(self, run_validator):
        run_validator.return_value = json.dumps(self.data)
        self.start_validation()
        res = ValidationResult.objects.get()
        assert res.task_error is None

        messages = res.validation_job.message_summary.all()

        assert messages.count() == 1
        assert messages[0].message_id == 'path.to.test_two'
        assert messages[0].message == 'message two'
        assert messages[0].compat_type == 'error'
        assert messages[0].addons_affected == 1

        # One `affected addon` per message
        assert ValidationResultAffectedAddon.objects.all().count() == 1


class TestEmailPreview(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestEmailPreview, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        addon = Addon.objects.get(pk=3615)
        self.topic = EmailPreviewTopic(addon)

    def test_csv(self):
        self.topic.send_mail('the subject', u'Hello Ivan Krsti\u0107',
                             from_email='admin@mozilla.org',
                             recipient_list=['funnyguy@mozilla.org'])
        r = self.client.get(reverse('zadmin.email_preview_csv',
                            args=[self.topic.topic]))
        assert r.status_code == 200
        rdr = csv.reader(StringIO(r.content))
        assert rdr.next() == ['from_email', 'recipient_list', 'subject',
                              'body']
        assert rdr.next() == ['admin@mozilla.org', 'funnyguy@mozilla.org',
                              'the subject', 'Hello Ivan Krsti\xc4\x87']


class TestMonthlyPick(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestMonthlyPick, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('zadmin.monthly_pick')
        addon = Addon.objects.get(pk=3615)
        MonthlyPick.objects.create(addon=addon,
                                   locale='zh-CN',
                                   blurb="test data",
                                   image="http://www.google.com")
        self.f = self.client.get(self.url).context['form'].initial_forms[0]
        self.initial = self.f.initial

    def test_form_initial(self):
        assert self.initial['addon'] == 3615
        assert self.initial['locale'] == 'zh-CN'
        assert self.initial['blurb'] == 'test data'
        assert self.initial['image'] == 'http://www.google.com'

    def test_success_insert(self):
        dupe = initial(self.f)
        del dupe['id']
        dupe.update(locale='fr')
        data = formset(initial(self.f), dupe, initial_count=1)
        self.client.post(self.url, data)
        assert MonthlyPick.objects.count() == 2
        assert MonthlyPick.objects.all()[1].locale == 'fr'

    def test_insert_no_image(self):
        dupe = initial(self.f)
        dupe.update(id='', image='', locale='en-US')
        data = formset(initial(self.f), dupe, initial_count=1)
        self.client.post(self.url, data)
        assert MonthlyPick.objects.count() == 2
        assert MonthlyPick.objects.all()[1].image == ''

    def test_success_insert_no_locale(self):
        dupe = initial(self.f)
        del dupe['id']
        del dupe['locale']
        data = formset(initial(self.f), dupe, initial_count=1)
        self.client.post(self.url, data)
        assert MonthlyPick.objects.count() == 2
        assert MonthlyPick.objects.all()[1].locale == ''

    def test_insert_long_blurb(self):
        dupe = initial(self.f)
        dupe.update(id='', blurb='x' * 201, locale='en-US')
        data = formset(initial(self.f), dupe, initial_count=1)
        r = self.client.post(self.url, data)
        assert r.context['form'].errors[1]['blurb'][0] == (
            'Ensure this value has at most 200 characters (it has 201).')

    def test_success_update(self):
        d = initial(self.f)
        d.update(locale='fr')
        r = self.client.post(self.url, formset(d, initial_count=1))
        assert r.status_code == 302
        assert MonthlyPick.objects.all()[0].locale == 'fr'

    def test_success_delete(self):
        d = initial(self.f)
        d.update(DELETE=True)
        self.client.post(self.url, formset(d, initial_count=1))
        assert MonthlyPick.objects.count() == 0

    def test_require_login(self):
        self.client.logout()
        r = self.client.get(self.url)
        assert r.status_code == 302


class TestFeatures(TestCase):
    fixtures = ['base/users', 'base/collections', 'base/addon_3615.json']

    def setUp(self):
        super(TestFeatures, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('zadmin.features')
        FeaturedCollection.objects.create(application=amo.FIREFOX.id,
                                          locale='zh-CN', collection_id=80)
        self.f = self.client.get(self.url).context['form'].initial_forms[0]
        self.initial = self.f.initial

    def test_form_initial(self):
        assert self.initial['application'] == amo.FIREFOX.id
        assert self.initial['locale'] == 'zh-CN'
        assert self.initial['collection'] == 80

    def test_form_attrs(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#features tr').attr('data-app') == str(amo.FIREFOX.id)
        assert doc('#features td.app').hasClass(amo.FIREFOX.short)
        assert doc('#features td.collection.loading').attr(
            'data-collection') == '80'
        assert doc('#features .collection-ac.js-hidden')
        assert not doc('#features .collection-ac[disabled]')

    def test_disabled_autocomplete_errors(self):
        """If any collection errors, autocomplete field should be enabled."""
        data = initial(self.f)
        data['collection'] = 999
        response = self.client.post(self.url, formset(data, initial_count=1))
        doc = pq(response.content)
        assert not doc('#features .collection-ac[disabled]')

    def test_required_app(self):
        data = initial(self.f)
        del data['application']
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.status_code == 200
        assert response.context['form'].errors[0]['application'] == (
            ['This field is required.'])
        assert response.context['form'].errors[0]['collection'] == (
            ['Invalid collection for this application.'])

    def test_bad_app(self):
        data = initial(self.f)
        data['application'] = 999
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.context['form'].errors[0]['application'] == [
            'Select a valid choice. 999 is not one of the available choices.']

    def test_bad_collection_for_app(self):
        data = initial(self.f)
        data['application'] = amo.THUNDERBIRD.id
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.context['form'].errors[0]['collection'] == (
            ['Invalid collection for this application.'])

    def test_bad_locale(self):
        data = initial(self.f)
        data['locale'] = 'klingon'
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.context['form'].errors[0]['locale'] == (
            ['Select a valid choice. klingon is not one of the available '
             'choices.'])

    def test_required_collection(self):
        data = initial(self.f)
        del data['collection']
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.context['form'].errors[0]['collection'] == (
            ['This field is required.'])

    def test_bad_collection(self):
        data = initial(self.f)
        data['collection'] = 999
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.context['form'].errors[0]['collection'] == (
            ['Invalid collection for this application.'])

    def test_success_insert(self):
        dupe = initial(self.f)
        del dupe['id']
        dupe['locale'] = 'fr'
        data = formset(initial(self.f), dupe, initial_count=1)
        self.client.post(self.url, data)
        assert FeaturedCollection.objects.count() == 2
        assert FeaturedCollection.objects.all()[1].locale == 'fr'

    def test_success_update(self):
        data = initial(self.f)
        data['locale'] = 'fr'
        response = self.client.post(self.url, formset(data, initial_count=1))
        assert response.status_code == 302
        assert FeaturedCollection.objects.all()[0].locale == 'fr'

    def test_success_delete(self):
        data = initial(self.f)
        data['DELETE'] = True
        self.client.post(self.url, formset(data, initial_count=1))
        assert FeaturedCollection.objects.count() == 0


class TestLookup(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestLookup, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('zadmin.search', args=['users', 'userprofile'])

    def test_logged_out(self):
        self.client.logout()
        assert self.client.get('%s?q=admin' % self.url).status_code == 403

    def check_results(self, q, expected):
        res = self.client.get(urlparams(self.url, q=q))
        assert res.status_code == 200
        content = json.loads(res.content)
        assert len(content) == len(expected)
        ids = [int(c['value']) for c in content]
        emails = [u'%s' % c['label'] for c in content]
        for d in expected:
            id = d['value']
            email = u'%s' % d['label']
            assert id in ids, (
                'Expected user ID "%s" not found' % id)
            assert email in emails, (
                'Expected username "%s" not found' % email)

    def test_lookup_wrong_model(self):
        self.url = reverse('zadmin.search', args=['doesnt', 'exist'])
        res = self.client.get(urlparams(self.url, q=''))
        assert res.status_code == 404

    def test_lookup_empty(self):
        users = UserProfile.objects.values('id', 'email')
        self.check_results('', [dict(
            value=u['id'], label=u['email']) for u in users])

    def test_lookup_by_id(self):
        self.check_results(self.user.id, [dict(value=self.user.id,
                                               label=self.user.email)])

    def test_lookup_by_email(self):
        self.check_results(self.user.email, [dict(value=self.user.id,
                                                  label=self.user.email)])

    def test_lookup_by_username(self):
        self.check_results(self.user.username, [dict(value=self.user.id,
                                                     label=self.user.email)])


class TestAddonSearch(amo.tests.ESTestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestAddonSearch, self).setUp()
        self.reindex(Addon)
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('zadmin.addon-search')

    def test_lookup_addon(self):
        res = self.client.get(urlparams(self.url, q='delicious'))
        # There's only one result, so it should just forward us to that page.
        assert res.status_code == 302


class TestAddonAdmin(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestAddonAdmin, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('admin:addons_addon_changelist')

    def test_basic(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        rows = doc('#result_list tbody tr')
        assert rows.length == 1
        assert rows.find('a').attr('href') == (
            '/en-US/admin/models/addons/addon/3615/')


class TestAddonManagement(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestAddonManagement, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.url = reverse('zadmin.addon_manage', args=[self.addon.slug])
        self.client.login(email='admin@mozilla.com')

    def test_can_manage_unlisted_addons(self):
        """Unlisted addons can be managed too."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    def test_addon_mixed_channels(self):
        first_version = self.addon.current_version
        second_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        first_expected_review_link = reverse(
            'editors.review', args=(self.addon.slug,))
        elms = doc('a[href="%s"]' % first_expected_review_link)
        assert len(elms) == 1
        assert elms[0].attrib['title'] == str(first_version.pk)
        assert elms[0].text == first_version.version

        second_expected_review_link = reverse(
            'editors.review', args=('unlisted', self.addon.slug,))
        elms = doc('a[href="%s"]' % second_expected_review_link)
        assert len(elms) == 1
        assert elms[0].attrib['title'] == str(second_version.pk)
        assert elms[0].text == second_version.version

    def _form_data(self, data=None):
        initial_data = {
            'status': '4',
            'form-0-status': '4',
            'form-0-id': '67442',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
        }
        if data:
            initial_data.update(data)
        return initial_data

    def test_addon_status_change(self):
        data = self._form_data({'status': '3'})
        r = self.client.post(self.url, data, follow=True)
        assert r.status_code == 200
        addon = Addon.objects.get(pk=3615)
        assert addon.status == 3

    def test_addon_file_status_change(self):
        data = self._form_data({'form-0-status': '1'})
        r = self.client.post(self.url, data, follow=True)
        assert r.status_code == 200
        file = File.objects.get(pk=67442)
        assert file.status == 1

    def test_addon_deleted_file_status_change(self):
        file = File.objects.get(pk=67442)
        file.version.update(deleted=True)
        data = self._form_data({'form-0-status': '1'})
        r = self.client.post(self.url, data, follow=True)
        # Form errors are silently suppressed.
        assert r.status_code == 200
        # But no change.
        assert file.status == 4

    @mock.patch.object(File, 'file_path',
                       amo.tests.AMOPaths().file_fixture_path(
                           'delicious_bookmarks-2.1.106-fx.xpi'))
    def test_regenerate_hash(self):
        version = Version.objects.create(addon_id=3615)
        file = File.objects.create(
            filename='delicious_bookmarks-2.1.106-fx.xpi', version=version)

        r = self.client.post(reverse('zadmin.recalc_hash', args=[file.id]))
        assert json.loads(r.content)[u'success'] == 1

        file = File.objects.get(pk=file.id)

        assert file.size, 'File size should not be zero'
        assert file.hash, 'File hash should not be empty'

    @mock.patch.object(File, 'file_path',
                       amo.tests.AMOPaths().file_fixture_path(
                           'delicious_bookmarks-2.1.106-fx.xpi'))
    def test_regenerate_hash_get(self):
        """ Don't allow GET """
        version = Version.objects.create(addon_id=3615)
        file = File.objects.create(
            filename='delicious_bookmarks-2.1.106-fx.xpi', version=version)

        r = self.client.get(reverse('zadmin.recalc_hash', args=[file.id]))
        assert r.status_code == 405  # GET out of here


class TestCompat(TestCompatibilityReportCronMixin, amo.tests.ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestCompat, self).setUp()
        self.url = reverse('zadmin.compat')
        self.client.login(email='admin@mozilla.com')
        self.app_version = FIREFOX_COMPAT[0]['main']

    def get_pq(self, **kw):
        response = self.client.get(self.url, kw)
        assert response.status_code == 200
        return pq(response.content)('#compat-results')

    def test_defaults(self):
        addon = self.populate()
        self.generate_reports(addon, good=0, bad=0, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.run_compatibility_report()

        r = self.client.get(self.url)
        assert r.status_code == 200
        table = pq(r.content)('#compat-results')
        assert table.length == 1
        assert table.find('.no-results').length == 1

    def check_row(self, tr, addon, good, bad, percentage, app_version):
        assert tr.length == 1
        version = addon.current_version.version

        name = tr.find('.name')
        assert name.find('.version').text() == 'v' + version
        assert name.remove('.version').text() == unicode(addon.name)
        assert name.find('a').attr('href') == addon.get_url_path()

        assert tr.find('.maxver').text() == (
            addon.compatible_apps[amo.FIREFOX].max.version)

        incompat = tr.find('.incompat')
        assert incompat.find('.bad').text() == str(bad)
        assert incompat.find('.total').text() == str(good + bad)
        percentage += '%'
        assert percentage in incompat.text(), (
            'Expected incompatibility to be %r' % percentage)

        assert tr.find('.version a').attr('href') == (
            reverse('devhub.versions.edit',
                    args=[addon.slug, addon.current_version.id]))
        assert tr.find('.reports a').attr('href') == (
            reverse('compat.reporter_detail', args=[addon.guid]))

        form = tr.find('.overrides form')
        assert form.attr('action') == reverse(
            'admin:addons_compatoverride_add')
        self.check_field(form, '_compat_ranges-TOTAL_FORMS', '1')
        self.check_field(form, '_compat_ranges-INITIAL_FORMS', '0')
        self.check_field(form, '_continue', '1')
        self.check_field(form, '_confirm', '1')
        self.check_field(form, 'addon', str(addon.id))
        self.check_field(form, 'guid', addon.guid)

        compat_field = '_compat_ranges-0-%s'
        self.check_field(form, compat_field % 'min_version', '0')
        self.check_field(form, compat_field % 'max_version', version)
        self.check_field(form, compat_field % 'min_app_version',
                         app_version + 'a1')
        self.check_field(form, compat_field % 'max_app_version',
                         app_version + '*')

    def check_field(self, form, name, val):
        assert form.find('input[name="%s"]' % name).val() == val

    def test_firefox_hosted(self):
        addon = self.populate()
        self.generate_reports(addon, good=0, bad=11, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.run_compatibility_report()

        tr = self.get_pq().find('tr[data-guid="%s"]' % addon.guid)
        self.check_row(tr, addon, good=0, bad=11, percentage='100.0',
                       app_version=self.app_version)

        # Add an override for this current app version.
        compat = CompatOverride.objects.create(addon=addon, guid=addon.guid)
        CompatOverrideRange.objects.create(
            compat=compat,
            app=amo.FIREFOX.id, min_app_version=self.app_version + 'a1',
            max_app_version=self.app_version + '*')

        # Check that there is an override for this current app version.
        tr = self.get_pq().find('tr[data-guid="%s"]' % addon.guid)
        assert tr.find('.overrides a').attr('href') == (
            reverse('admin:addons_compatoverride_change', args=[compat.id]))

    def test_non_default_version(self):
        app_version = FIREFOX_COMPAT[2]['main']
        addon = self.populate()
        self.generate_reports(addon, good=0, bad=11, app=amo.FIREFOX,
                              app_version=app_version)
        self.run_compatibility_report()

        pq = self.get_pq()
        assert pq.find('tr[data-guid="%s"]' % addon.guid).length == 0

        appver = app_version
        tr = self.get_pq(appver=appver)('tr[data-guid="%s"]' % addon.guid)
        self.check_row(tr, addon, good=0, bad=11, percentage='100.0',
                       app_version=app_version)

    def test_minor_versions(self):
        addon = self.populate()
        self.generate_reports(addon, good=0, bad=1, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.generate_reports(addon, good=1, bad=2, app=amo.FIREFOX,
                              app_version=self.app_version + 'a2')
        self.run_compatibility_report()

        tr = self.get_pq(ratio=0.0, minimum=0).find('tr[data-guid="%s"]' %
                                                    addon.guid)
        self.check_row(tr, addon, good=1, bad=3, percentage='75.0',
                       app_version=self.app_version)

    def test_ratio(self):
        addon = self.populate()
        self.generate_reports(addon, good=11, bad=11, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.run_compatibility_report()

        # Should not show up for > 80%.
        pq = self.get_pq()
        assert pq.find('tr[data-guid="%s"]' % addon.guid).length == 0

        # Should not show up for > 50%.
        tr = self.get_pq(ratio=.5).find('tr[data-guid="%s"]' % addon.guid)
        assert tr.length == 0

        # Should show up for > 40%.
        tr = self.get_pq(ratio=.4).find('tr[data-guid="%s"]' % addon.guid)
        assert tr.length == 1

    def test_min_incompatible(self):
        addon = self.populate()
        self.generate_reports(addon, good=0, bad=11, app=amo.FIREFOX,
                              app_version=self.app_version)
        self.run_compatibility_report()

        # Should show up for >= 10.
        pq = self.get_pq()
        assert pq.find('tr[data-guid="%s"]' % addon.guid).length == 1

        # Should show up for >= 0.
        tr = self.get_pq(minimum=0).find('tr[data-guid="%s"]' % addon.guid)
        assert tr.length == 1

        # Should not show up for >= 20.
        tr = self.get_pq(minimum=20).find('tr[data-guid="%s"]' % addon.guid)
        assert tr.length == 0


class TestMemcache(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestMemcache, self).setUp()
        self.url = reverse('zadmin.memcache')
        cache.set('foo', 'bar')
        self.client.login(email='admin@mozilla.com')

    def test_login(self):
        self.client.logout()
        assert self.client.get(self.url).status_code == 302

    def test_can_clear(self):
        self.client.post(self.url, {'yes': 'True'})
        assert cache.get('foo') is None

    def test_cant_clear(self):
        self.client.post(self.url, {'yes': 'False'})
        assert cache.get('foo') == 'bar'


class TestElastic(amo.tests.ESTestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestElastic, self).setUp()
        self.url = reverse('zadmin.elastic')
        self.client.login(email='admin@mozilla.com')

    def test_login(self):
        self.client.logout()
        self.assertLoginRedirects(
            self.client.get(self.url), to='/en-US/admin/elastic')


class TestEmailDevs(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestEmailDevs, self).setUp()
        self.login('admin')
        self.addon = Addon.objects.get(pk=3615)

    def post(self, recipients='eula', subject='subject', message='msg',
             preview_only=False):
        return self.client.post(reverse('zadmin.email_devs'),
                                dict(recipients=recipients, subject=subject,
                                     message=message,
                                     preview_only=preview_only))

    def test_preview(self):
        res = self.post(preview_only=True)
        self.assertNoFormErrors(res)
        preview = EmailPreviewTopic(topic='email-devs')
        assert [e.recipient_list for e in preview.filter()] == ['del@icio.us']
        assert len(mail.outbox) == 0

    def test_actual(self):
        subject = 'about eulas'
        message = 'message about eulas'
        res = self.post(subject=subject, message=message)
        self.assertNoFormErrors(res)
        self.assert3xx(res, reverse('zadmin.email_devs'))
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == subject
        assert mail.outbox[0].body == message
        assert mail.outbox[0].to == ['del@icio.us']
        assert mail.outbox[0].from_email == settings.DEFAULT_FROM_EMAIL

    def test_only_eulas(self):
        self.addon.update(eula=None)
        res = self.post()
        self.assertNoFormErrors(res)
        assert len(mail.outbox) == 0

    def test_sdk_devs(self):
        (File.objects.filter(version__addon=self.addon)
                     .update(jetpack_version='1.5'))
        res = self.post(recipients='sdk')
        self.assertNoFormErrors(res)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['del@icio.us']

    def test_only_sdk_devs(self):
        res = self.post(recipients='sdk')
        self.assertNoFormErrors(res)
        assert len(mail.outbox) == 0

    def test_only_extensions(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        res = self.post(recipients='all_extensions')
        self.assertNoFormErrors(res)
        assert len(mail.outbox) == 1

    def test_ignore_deleted_always(self):
        self.addon.update(status=amo.STATUS_DELETED)
        for name, label in DevMailerForm._choices:
            res = self.post(recipients=name)
            self.assertNoFormErrors(res)
            assert len(mail.outbox) == 0

    def test_exclude_pending_for_addons(self):
        self.addon.update(status=amo.STATUS_PENDING)
        for name, label in DevMailerForm._choices:
            if name in ('payments', 'desktop_apps'):
                continue
            res = self.post(recipients=name)
            self.assertNoFormErrors(res)
            assert len(mail.outbox) == 0

    def test_depreliminary_addon_devs(self):
        # We just need a user for the log(), it would normally be task user.
        ActivityLog.create(
            amo.LOG.PRELIMINARY_ADDON_MIGRATED, self.addon,
            details={'email': True}, user=self.addon.authors.get())
        res = self.post(recipients='depreliminary')
        self.assertNoFormErrors(res)
        self.assert3xx(res, reverse('zadmin.email_devs'))
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['del@icio.us']
        assert mail.outbox[0].from_email == settings.DEFAULT_FROM_EMAIL

    def test_only_depreliminary_addon_devs(self):
        res = self.post(recipients='depreliminary')
        self.assertNoFormErrors(res)
        self.assert3xx(res, reverse('zadmin.email_devs'))
        assert len(mail.outbox) == 0

    def test_we_only_email_devs_that_need_emailing(self):
        # Doesn't matter the reason, but this addon doesn't get an email.
        ActivityLog.create(
            amo.LOG.PRELIMINARY_ADDON_MIGRATED, self.addon,
            details={'email': False}, user=self.addon.authors.get())
        res = self.post(recipients='depreliminary')
        self.assertNoFormErrors(res)
        self.assert3xx(res, reverse('zadmin.email_devs'))
        assert len(mail.outbox) == 0


class TestFileDownload(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestFileDownload, self).setUp()

        assert self.client.login(email='admin@mozilla.com')

        self.file = open(get_image_path('animated.png'), 'rb')
        resp = self.client.post(reverse('devhub.upload'),
                                {'upload': self.file})
        assert resp.status_code == 302

        self.upload = FileUpload.objects.get()
        self.url = reverse('zadmin.download_file', args=[self.upload.uuid.hex])

    def test_download(self):
        """Test that downloading file_upload objects works."""
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert resp.content == self.file.read()


class TestPerms(TestCase):
    fixtures = ['base/users']

    FILE_ID = '1234567890abcdef1234567890abcdef'

    def assert_status(self, view, status, **kw):
        """Check that requesting the named view returns the expected status."""

        assert self.client.get(reverse(view, kwargs=kw)).status_code == status

    def test_admin_user(self):
        # Admin should see views with Django's perm decorator and our own.
        assert self.client.login(email='admin@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status('zadmin.env', 200)
        self.assert_status('zadmin.settings', 200)
        self.assert_status('zadmin.langpacks', 200)
        self.assert_status('zadmin.download_file', 404, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 200)
        self.assert_status('zadmin.monthly_pick', 200)
        self.assert_status('zadmin.features', 200)
        self.assert_status('discovery.module_admin', 200)

    def test_staff_user(self):
        # Staff users have some privileges.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Staff', rules='AdminTools:View')
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status('zadmin.env', 200)
        self.assert_status('zadmin.settings', 200)
        self.assert_status('zadmin.langpacks', 200)
        self.assert_status('zadmin.download_file', 404, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 200)
        self.assert_status('zadmin.monthly_pick', 200)
        self.assert_status('zadmin.features', 200)
        self.assert_status('discovery.module_admin', 200)

    def test_sr_reviewers_user(self):
        # Sr Reviewers users have only a few privileges.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Sr Reviewer',
                                     rules='ReviewerAdminTools:View')
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status('zadmin.langpacks', 200)
        self.assert_status('zadmin.download_file', 404, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 200)
        self.assert_status('zadmin.env', 403)
        self.assert_status('zadmin.settings', 403)

    def test_unprivileged_user(self):
        # Unprivileged user.
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 403)
        self.assert_status('zadmin.env', 403)
        self.assert_status('zadmin.settings', 403)
        self.assert_status('zadmin.langpacks', 403)
        self.assert_status('zadmin.download_file', 403, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 403)
        self.assert_status('zadmin.monthly_pick', 403)
        self.assert_status('zadmin.features', 403)
        self.assert_status('discovery.module_admin', 403)
        # Anonymous users should also get a 403.
        self.client.logout()
        self.assertLoginRedirects(
            self.client.get(reverse('zadmin.index')), to='/en-US/admin/')


class TestUserProfileAdmin(TestCase):

    def setUp(self):
        super(TestUserProfileAdmin, self).setUp()
        self.user = user_factory(email='admin@mozilla.com')
        self.grant_permission(self.user, '*:*')
        self.login(self.user)

    def test_delete_does_hard_delete(self):
        user_to_delete = user_factory()
        user_to_delete_pk = user_to_delete.pk
        url = reverse('admin:users_userprofile_delete',
                      args=[user_to_delete.pk])
        response = self.client.post(url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 200
        assert not UserProfile.objects.filter(id=user_to_delete_pk).exists()
