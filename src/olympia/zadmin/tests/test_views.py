# -*- coding: utf-8 -*-
import csv
import json
import os

from cStringIO import StringIO

from django.conf import settings
from django.core import mail
from django.core.cache import cache

import mock

from pyquery import PyQuery as pq

import olympia

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, CompatOverride, CompatOverrideRange
from olympia.amo.tests import (
    TestCase, formset, initial, user_factory, version_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.bandwagon.models import FeaturedCollection, MonthlyPick
from olympia.compat import FIREFOX_COMPAT
from olympia.compat.tests import TestCompatibilityReportCronMixin
from olympia.files.models import File, FileUpload
from olympia.users.models import UserProfile
from olympia.versions.models import Version
from olympia.zadmin.forms import DevMailerForm
from olympia.zadmin.models import EmailPreviewTopic


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
        # Can access with full admin.
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Redirected because no permissions if not logged in.
        self.client.logout()
        response = self.client.get(url)
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

        # Redirected when logged in without enough permissions.
        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.client.login(email='staffperson@m.c')
        response = self.client.get(url)
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

        # Can access with a "is_staff" user.
        self.grant_permission(user, 'Admin:Something')
        response = self.client.get(url)
        assert response.status_code == 200


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
            'reviewers.review', args=(self.addon.slug,))
        elms = doc('a[href="%s"]' % first_expected_review_link)
        assert len(elms) == 1
        assert elms[0].attrib['title'] == str(first_version.pk)
        assert elms[0].text == first_version.version

        second_expected_review_link = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug,))
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
        group = Group.objects.create(name='Staff', rules='Admin:Tools')
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
