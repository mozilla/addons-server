import test_utils
from nose.tools import eq_

import amo
from search import forms


class TestSearchForm(test_utils.TestCase):
    fixtures = ('base/appversion', 'addons/persona',)

    def test_get_app_versions(self):
        actual = forms.get_app_versions(amo.FIREFOX)
        expected = [('any', 'Any'), ('3.6', '3.6'),
                    ('3.5', '3.5'), ('3.0', '3.0'), ]

        # So you added a new appversion and this broke?  Sorry about that.
        eq_(actual, expected)
