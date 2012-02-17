import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.tests import assert_required, formset, initial
from amo.urlresolvers import reverse
from addons.models import BlacklistedSlug
from addons.utils import ReverseNameLookup
from applications.models import AppVersion
from devhub.views import packager_path


class TestPackager(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/appversion',
                'base/addon_3615']

    def setUp(self):
        self.url = reverse('devhub.package_addon')

        ctx = self.client.get(self.url).context['compat_forms']
        self.compat_form = initial(ctx.initial_forms[1])

    def _form_data(self, data={}, compat_forms=None):
        """Build the initial data set for the form."""
        initial_data = {'author_name': 'author',
                        'contributors': '',
                        'description': '',
                        'name': 'My Addon',
                        'package_name': 'my_addon',
                        'id': 'foo@bar.com',
                        'version': '1.2.3'}
        if not compat_forms:
            compat_forms = [self.compat_form]
        initial_data.update(formset(*compat_forms))
        if data:
            initial_data.update(data)
        return initial_data

    def test_login_optional(self):
        eq_(self.client.get(self.url).status_code, 200)

        self.client.login(username='regular@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_form_initial(self):
        """Ensure that the initial forms for each application are present."""
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        rows = pq(r.content)('#supported-apps li.row')
        classes = [a.short for a in amo.APP_USAGE]
        eq_(rows.length, len(classes))
        for app_class, label in zip(classes, rows('label.app')):
            assert pq(label).hasClass(app_class), (
                'Label for application %r not found' % app_class)

    def test_success(self):
        """
        Test that a proper set of data will pass validation, pass through
        to the success view, and check if the .zip file exists.
        """
        self.compat_form = {'enabled': 'on', 'min_ver': '86', 'max_ver': '114'}
        data = self._form_data()
        pkg_name = data['package_name']
        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, reverse('devhub.package_addon_success',
                                        args=[pkg_name]), 302)
        eq_(r.status_code, 200)
        d = pq(r.content)('#packager-download')
        eq_(d.attr('data-downloadurl'),
            reverse('devhub.package_addon_json', args=[pkg_name]))

        assert os.path.isfile(packager_path(pkg_name)), (
            'Package was not created.')
        pkg = self.client.get(reverse('devhub.package_addon_download',
                              args=[pkg_name]))
        eq_(pkg.status_code, 200)
        eq_(pkg['content-type'], 'application/zip')
        eq_(pkg['X-SENDFILE'], packager_path(pkg_name))

    def test_name_required(self):
        r = self.client.post(self.url, self._form_data({'package_name': ''}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'This field is required.')

    def test_name_trademarks(self):
        """Test that the add-on name cannot contain Mozilla trademarks."""
        r = self.client.post(self.url, self._form_data({'name': 'Mozilla <3'}))
        self.assertFormError(r, 'basic_form', 'name',
            'Add-on names should not contain Mozilla trademarks.')

    def test_name_taken(self):
        """Test that the add-on name is not already taken."""
        ReverseNameLookup().add('Delicious Bookmarks', 34)
        data = self._form_data({'name': 'Delicious Bookmarks'})
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'basic_form', 'name',
            'This name is already in use. Please choose another.')

    def test_name_minlength(self):
        data = self._form_data({'name': 'abcd'})
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'basic_form', 'name',
            'Ensure this value has at least 5 characters (it has 4).')

    def test_name_maxlength(self):
        data = self._form_data({'name': 'x' * 51})
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'basic_form', 'name',
            'Ensure this value has at most 50 characters (it has 51).')

    def test_package_name_required(self):
        r = self.client.post(self.url, self._form_data({'package_name': ''}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'This field is required.')

    def test_package_name_minlength(self):
        data = self._form_data({'package_name': 'abcd'})
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'basic_form', 'package_name',
            'Ensure this value has at least 5 characters (it has 4).')

    def test_package_name_maxlength(self):
        data = self._form_data({'package_name': 'x' * 51})
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'basic_form', 'package_name',
            'Ensure this value has at most 50 characters (it has 51).')

    def test_package_name_format(self):
        error = ('Enter a valid package name consisting of letters, numbers, '
                 'or underscores.')
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'addon name'}))
        self.assertFormError(r, 'basic_form', 'package_name', error)
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'addon-name'}))
        self.assertFormError(r, 'basic_form', 'package_name', error)

    def test_package_name_uppercase(self):
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'ADDON_NAME'}))
        eq_(r.context['basic_form'].errors, {})

    def test_package_name_taken(self):
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'a3615'}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'This package name is already in use.')

    def test_package_name_blacklisted(self):
        BlacklistedSlug.objects.create(name='slap_tickle')
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'slap_tickle'}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'The package name cannot be: slap_tickle.')

    def test_version(self):
        """Test that the add-on version is properly validated."""
        r = self.client.post(self.url,
                             self._form_data({'version': 'invalid version'}))
        self.assertFormError(r, 'basic_form', 'version',
                             'The version string is invalid.')

    def test_id(self):
        """Test that the add-on id is properly validated."""
        r = self.client.post(self.url, self._form_data({'id': 'invalid id'}))
        self.assertFormError(
                r, 'basic_form', 'id',
                'The add-on ID must be a UUID string or an email address.')

    def test_firefox_required(self):
        """Ensure that at least one target application is required."""
        self.compat_form = {}
        r = self.client.post(self.url, self._form_data())
        eq_(r.context['compat_forms'].non_form_errors(),
            ['Firefox is a required target application.'])

    def test_enabled_apps_version_required(self):
        """Min/Max Version fields should be required for enabled apps."""
        forms = [self.compat_form, {'enabled': 'on'}]
        r = self.client.post(self.url, self._form_data(compat_forms=forms))
        assert_required(r.context['compat_forms'].errors[1]['min_ver'][0])
        assert_required(r.context['compat_forms'].errors[1]['max_ver'][0])

    def test_version_order(self):
        """Test that the min version is lte the max version."""
        self.compat_form['enabled'] = 'on'
        self.compat_form['min_ver'] = '114'
        self.compat_form['max_ver'] = '86'
        r = self.client.post(self.url, self._form_data())
        eq_(r.context['compat_forms'].errors[0]['__all__'][0],
            'Min version must be less than Max version.')

    @patch.object(settings, 'DEFAULT_MINVER', '3.6')
    def test_default_firefox_minver(self):
        eq_(len(AppVersion.objects.filter(application__id=amo.FIREFOX.id,
                                          version='3.6')), 1)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        s = pq(r.content)('select#id_form-0-min_ver option[selected]').text()
        eq_(s, '3.6')

    @patch.object(settings, 'DEFAULT_MINVER', '999.0')
    def test_no_default_firefox_minver(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        s = pq(r.content)('select#id_form-0-min_ver option[selected]').text()
        assert s != '3.6', (
            'The Firefox minVer default should not be set on POST.')

    @patch.object(settings, 'DEFAULT_MINVER', '3.6')
    def test_no_default_firefox_minver_on_post(self):
        self.compat_form['min_ver'] = '114'
        r = self.client.post(self.url, self._form_data())
        s = pq(r.content)('select#id_form-0-min_ver option[selected]').text()
        assert s != '3.6', (
            'The Firefox minVer default should not be set on POST.')


class TestPackagerDownload(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/appversion',
                'base/addon_3615']

    def setUp(self):
        self.url = lambda f: reverse('devhub.package_addon_json', args=[f])

    def _prep_mock_package(self, name):
        """Prep a fake package to be downloaded."""
        path = packager_path(name)
        with open(path, mode='w') as package:
            package.write('ready')
        return path

    def _unprep_package(self, name):
        package = packager_path(name)
        if storage.exists(package):
            storage.delete(package)

    def test_package_pending(self):
        """
        Test that an unavailable message is returned when the file isn't ready
        to be downloaded yet.
        """
        self._unprep_package('foobar')
        r = self.client.get(self.url('foobar'))
        # Ensure a deleted file returns an empty message.
        eq_(r.content, 'null')

    def test_package_success(self):
        """Ensure a completed file returns the file data."""
        dst = self._prep_mock_package('foobar')
        r = self.client.get(self.url('foobar'))
        data = json.loads(r.content)

        # Size in kB.
        eq_(data['size'], round(os.path.getsize(dst) / 1024, 1))

        eq_(data['filename'], os.path.basename(dst))

        eq_(data['download_url'], reverse('devhub.package_addon_download',
                                          args=['foobar']))
        assert data['download_url'].endswith('.zip'), (
            'Expected filename to end with .zip.')

        pkg = self.client.get(data['download_url'])
        eq_(pkg.status_code, 200)
        eq_(pkg['content-type'], 'application/zip')
        eq_(pkg['X-SENDFILE'], dst)

        self._unprep_package('foobar')

    def test_login_optional(self):
        self._prep_mock_package('foobar')

        url = self.url('foobar')
        eq_(self.client.get(url).status_code, 200)

        self.client.login(username='regular@mozilla.com', password='password')
        eq_(self.client.get(url).status_code, 200)

        self._unprep_package('foobar')
