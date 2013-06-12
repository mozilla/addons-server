import mock
from nose.tools import eq_

from django import forms

import amo.tests
from files.utils import WebAppParser


class TestWebAppParser(amo.tests.TestCase):

    @mock.patch('files.utils.WebAppParser.get_json_data')
    def test_no_developer_name(self, get_json_data):
        get_json_data.return_value = {
            'name': 'Blah'
        }
        with self.assertRaises(forms.ValidationError) as e:
            # The argument to parse() is supposed to be a filename, it doesn't
            # matter here though since we are mocking get_json_data().
            WebAppParser().parse('')
        eq_(e.exception.messages, ["Developer name is required in the manifest"
                                   " in order to display it on the app's "
                                   "listing."])

    @mock.patch('files.utils.WebAppParser.get_json_data')
    def test_empty_developer_object(self, get_json_data):
        get_json_data.return_value = {
            'name': 'Blah',
            'developer': {}
        }
        with self.assertRaises(forms.ValidationError) as e:
            # The argument to parse() is supposed to be a filename, it doesn't
            # matter here though since we are mocking get_json_data().
            WebAppParser().parse('')
        eq_(e.exception.messages, ["Developer name is required in the manifest"
                                   " in order to display it on the app's "
                                   "listing."])

    @mock.patch('files.utils.WebAppParser.get_json_data')
    def test_developer_name(self, get_json_data):
        get_json_data.return_value = {
            'name': 'Blah',
            'developer': {
                'name': 'Mozilla Marketplace Testing'
            }
        }
        # The argument to parse() is supposed to be a filename, it doesn't
        # matter here though since we are mocking get_json_data().
        parsed_results = WebAppParser().parse('')
        eq_(parsed_results['developer_name'], 'Mozilla Marketplace Testing')
