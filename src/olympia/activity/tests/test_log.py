# -*- coding: utf-8 -*-
import json

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import addon_factory, TestCase
from olympia.users.models import UserProfile


class LogTest(TestCase):
    def setUp(self):
        super(LogTest, self).setUp()
        u = UserProfile.objects.create(username='foo')
        core.set_user(u)

    def test_details(self):
        """
        If we get details, verify they are stored as JSON, and we get out what
        we put in.
        """
        addon = addon_factory(name=u'kümar is awesome')
        magic = {'title': u'nô', 'body': u'wày!'}
        al = ActivityLog.create(amo.LOG.DELETE_RATING, 1, addon, details=magic)

        assert al.details == magic
        assert al._details == json.dumps(magic)
