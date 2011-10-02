import json
import os

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.tests import assert_required, formset, initial
from amo.urlresolvers import reverse
from addons.models import BlacklistedSlug
from devhub.views import packager_path


class TestAddOnPackager(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/appversion',
                'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.package_addon')

        ctx = self.client.get(self.url).context['compat_forms']
        self.compat_form = initial(ctx.initial_forms[1])

    def _form_data(self, data={}, compat_forms=None):
        """Build the initial data set for the form."""
        initial_data = {'author_name': 'author',
                        'contributors': '',
                        'description': '',
                        'name': 'name',
                        'package_name': 'name',
                        'id': 'foo@bar.com',
                        'version': '1.2.3'}
        if not compat_forms:
            compat_forms = [self.compat_form]
        initial_data.update(formset(*compat_forms))
        if data:
            initial_data.update(data)
        return initial_data

    def test_required_login(self):
        self.client.logout()
        r = self.client.get(self.url)
        eq_(r.status_code, 302)

    def test_form_initial(self):
        """Ensure that the initial forms for each application are present."""
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        rows = pq(r.content)('.supported-apps li.row')
        classes = [a.short for a in amo.APP_USAGE]
        eq_(rows.length, len(classes))
        for app_class, label in zip(classes, rows('label.app')):
            assert pq(label).hasClass(app_class), (
                'Label for application %r not found' % app_class)

    def test_validate_pass(self):
        """
        Test that a proper set of data will pass validation and pass through
        to the success view.
        """
        self.compat_form['enabled'] = 'on'
        self.compat_form['min_ver'] = '86'
        self.compat_form['max_ver'] = '114'
        r = self.client.post(self.url, self._form_data(), follow=True)
        eq_(r.status_code, 200)

    def test_validate_name(self):
        """Test that the add-on name is properly validated."""
        r = self.client.post(self.url, self._form_data({'name': 'Mozilla <3'}))
        self.assertFormError(
                r, 'basic_form', 'name',
                'Add-on names should not contain Mozilla trademarks.')

    def test_validate_package_name_required(self):
        r = self.client.post(self.url, self._form_data({'package_name': ''}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'This field is required.')

    def test_validate_package_name_format(self):
        error = ('Enter a valid package name consisting of letters, numbers, '
                 'or underscores.')
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'addon name'}))
        self.assertFormError(r, 'basic_form', 'package_name', error)
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'addon-name'}))
        self.assertFormError(r, 'basic_form', 'package_name', error)

    def test_validate_package_name_taken(self):
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'a3615'}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'This package name is already in use.')

    def test_validate_package_name_blacklisted(self):
        BlacklistedSlug.objects.create(name='slap_tickle')
        r = self.client.post(self.url,
                             self._form_data({'package_name': 'slap_tickle'}))
        self.assertFormError(r, 'basic_form', 'package_name',
                             'The package name cannot be: slap_tickle.')

    def test_validate_version(self):
        """Test that the add-on version is properly validated."""
        r = self.client.post(self.url,
                             self._form_data({'version': 'invalid version'}))
        self.assertFormError(r, 'basic_form', 'version',
                             'The version string is invalid.')

    def test_validate_id(self):
        """Test that the add-on id is properly validated."""
        r = self.client.post(self.url, self._form_data({'id': 'invalid id'}))
        self.assertFormError(
                r, 'basic_form', 'id',
                'The add-on ID must be a UUID string or an email address.')

    def test_app_required(self):
        """Ensure that at least one target application is required."""
        self.compat_form = {}
        r = self.client.post(self.url, self._form_data())
        eq_(r.context['compat_forms'].non_form_errors(),
            ['At least one target application must be selected.'])

    def test_enabled_apps_version_required(self):
        """Min/Max Version fields should be required for enabled apps."""
        forms = [self.compat_form, {'enabled': 'on'}]
        r = self.client.post(self.url, self._form_data(compat_forms=forms))
        assert_required(r.context['compat_forms'].errors[1]['min_ver'][0])
        assert_required(r.context['compat_forms'].errors[1]['max_ver'][0])

    def test_validate_version_order(self):
        """Test that the min version is lte the max version."""
        self.compat_form['enabled'] = 'on'
        self.compat_form['min_ver'] = '114'
        self.compat_form['max_ver'] = '86'
        r = self.client.post(self.url, self._form_data())
        eq_(r.context['compat_forms'].errors[0]['__all__'][0],
            'Min version must be less than Max version.')


class TestPackagerJSON(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/appversion']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def package_json(self, id):
        return reverse('devhub.package_addon_json', args=[id])

    def _prep_mock_package(self, name):
        """Prep a fake package to be downloaded."""
        path = packager_path(name)
        with open(path, mode='w') as package:
            package.write('ready')

    def _unprep_package(self, name):
        package = packager_path(name)
        if os.path.exists(package):
            os.remove(package)

    def test_json_unavailable(self):
        """
        Test that an unavailable message is returned when the file isn't ready
        to be downloaded yet.
        """

        # Ensure a deleted file returns an empty message.
        self._unprep_package('foobar')
        r = self.client.get(self.package_json('foobar'))
        eq_(r.content, 'null')

        # Ensure a completed file returns the file data.
        self._prep_mock_package('foobar')
        r = self.client.get(self.package_json('foobar'))
        data = json.loads(r.content)

        assert 'download_url' in data
        pack = self.client.get(data['download_url'])
        eq_(pack.status_code, 200)

        assert 'size' in data
        assert isinstance(data['size'], (int, float))

        self._unprep_package('foobar')
