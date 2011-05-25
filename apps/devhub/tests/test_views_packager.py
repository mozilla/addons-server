import json
import os

from django.conf import settings
import test_utils

from nose.tools import eq_
from pyquery import PyQuery as pq

from amo.tests import formset, initial
from amo.urlresolvers import reverse
from devhub.views import packager_path


class TestAddOnPackager(test_utils.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/appversion']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.package_addon = reverse('devhub.package_addon')

        ctx = self.client.get(self.package_addon).context['compat_forms']
        self.compat_form = initial(ctx.initial_forms[1])

    def test_has_versions(self):
        """Test that versions are listed in targetApplication fields."""
        r = self.client.get(self.package_addon)
        eq_(r.status_code, 200)

        doc = pq(r.content)
        # Assert that the first dropdown (Firefox) has at least thirty items.
        assert len(doc('.compat_form select').children()) > 30

    def test_no_mozilla(self):
        """
        Test that the Mozilla browser is not represented in the
        targetApplication list.
        """
        r = self.client.get(self.package_addon)
        eq_(r.status_code, 200)

        doc = pq(r.content)
        for label in doc('.compat_form label'):
            assert pq(label).text() != 'Mozilla'

    def _form_data(self, data=None, compat_form=True):
        """Build the initial data set for the form."""

        initial_data = {'author_name': 'author',
                        'contributors': '',
                        'description': '',
                        'name': 'name',
                        'id': 'foo@bar.com',
                        'version': '1.2.3'}

        if compat_form:
            initial_data.update(formset(self.compat_form))

        if data:
            initial_data.update(data)
        return initial_data

    def test_validate_pass(self):
        """
        Test that a proper set of data will pass validation and pass through
        to the success view.
        """
        self.compat_form['enabled'] = 'on'
        self.compat_form['min_ver'] = '86'
        self.compat_form['max_ver'] = '114'
        r = self.client.post(self.package_addon, self._form_data(),
                             follow=True)
        eq_(r.status_code, 200)
        eq_(pq(pq(r.content)('h3')[0]).text(), 'Add-on packaged successfully!')

    def test_validate_name(self):
        """Test that the add-on name is properly validated."""
        r = self.client.post(self.package_addon,
                             self._form_data({'name': 'Mozilla App'}))
        self.assertFormError(
                r, 'basic_form', 'name',
                'Add-on names should not contain Mozilla trademarks.')

    def test_validate_version(self):
        """Test that the add-on version is properly validated."""
        r = self.client.post(self.package_addon,
                             self._form_data({'version': 'invalid version'}))
        self.assertFormError(
                r, 'basic_form', 'version',
                'The version string is invalid.')

    def test_validate_id(self):
        """Test that the add-on id is properly validated."""
        r = self.client.post(self.package_addon,
                             self._form_data({'id': 'invalid id'}))
        self.assertFormError(
                r, 'basic_form', 'id',
                'The add-on ID must be a UUID string or an email address.')

    def test_validate_version_enabled(self):
        """Test that at least one version must be enabled."""
        # Nothing needs to be done; no apps are enabled by default.
        r = self.client.post(self.package_addon, self._form_data())
        assert not r.context['compat_forms'].is_valid()

    def test_validate_version_order(self):
        """Test that the min version is lte the max version."""
        self.compat_form['enabled'] = 'on'
        self.compat_form['min_ver'] = '114'
        self.compat_form['max_ver'] = '86'
        r = self.client.post(self.package_addon,
                             self._form_data())
        eq_(r.context['compat_forms'].errors[0]['__all__'][0],
            'Min version must be less than Max version.')

    def test_required_login(self):
        self.client.logout()
        r = self.client.get(self.package_addon)
        eq_(r.status_code, 302)


class TestPackagerJSON(test_utils.TestCase):
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

