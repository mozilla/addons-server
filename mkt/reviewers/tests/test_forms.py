from nose.tools import eq_

import amo
import amo.tests
from mkt.reviewers.forms import AppQueueSearchForm


class TestAppQueueSearchForm(amo.tests.TestCase):

    def setUp(self):
        self.data = {
            'text_query': 'as you think, so shall you become',
            'admin_review': False,
            'has_editor_comment': False,
            'has_info_request': False,
            'waiting_time_days': '10',
            'device_type_ids': ['1'],
            'premium_type_ids': ['2'],
        }

    def test_basic(self):
        """Test the form doesn't crap out."""
        self.check_valid(True)

    def test_has_admin_review(self):
        self.data['admin_review'] = True
        self.check_valid(True)

    def test_has_editor_comment(self):
        self.data['has_editor_comment'] = True
        self.check_valid(True)

    def test_has_info_request(self):
        self.data['has_info_request'] = True
        self.check_valid(True)

    def test_waiting_time_days(self):
        """Test waiting_time_days only takes numbers."""
        for choice in (999, 'real living is living for others'):
            self.data['waiting_time_days'] = choice
            self.check_valid(False)

        for choice in ('', '5'):
            self.data['waiting_time_days'] = choice
            self.check_valid(True)

    def test_device_type(self):
        """Test only accept amo.DEVICE_TYPES"""
        # Put in out-of-range numbers and check form not valid.
        for choice in ([45], [1, 999]):
            self.data['device_type_ids'] = choice
            self.check_valid(False)

        for choice in ([amo.DEVICE_DESKTOP.id, amo.DEVICE_MOBILE.id],
                       [amo.DEVICE_TABLET.id]):
            self.data['device_type_ids'] = choice
            self.check_valid(True)

    def test_premium(self):
        """Test only accept amo.PREMIUM"""
        # Put in out-of-range numbers and check form not valid.
        for choice in ([45], [1, 32]):
            self.data['premium_type_ids'] = choice
            self.check_valid(False)

        for choice in ([amo.ADDON_FREE, amo.ADDON_PREMIUM],
                       [amo.ADDON_FREE_INAPP]):
            self.data['premium_type_ids'] = choice
            self.check_valid(True)

    def check_valid(self, valid):
        form = AppQueueSearchForm(self.data)
        eq_(form.is_valid(), valid)
