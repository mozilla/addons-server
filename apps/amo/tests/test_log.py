"""Tests for the activitylog."""
from datetime import datetime

import test_utils
from nose.tools import eq_

import amo
from addons.models import Addon
from users.models import UserProfile


class LogTest(test_utils.TestCase):
    def setUp(self):
        u = UserProfile.objects.create(username='foo')
        amo.set_user(u)

    def test_details(self):
        """
        If we get details, verify they are stored as JSON, and we get out what
        we put in.
        """
        a = Addon.objects.create(name='kumar is awesome',
                                type=amo.ADDON_EXTENSION)
        magic = dict(title='no', body='way!')
        al = amo.log(amo.LOG.DELETE_REVIEW, 1, a, details=magic)

        eq_(al.details, magic)
        eq_(al._details, '{"body": "way!", "title": "no"}')

    def test_created(self):
        """
        Verify that we preserve the create date.
        """
        al = amo.log(amo.LOG.CUSTOM_TEXT, 'hi', created=datetime(2009, 1, 1))

        eq_(al.created, datetime(2009, 1, 1))

