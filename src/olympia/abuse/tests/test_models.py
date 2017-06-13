# -*- coding: utf-8 -*-
from django.conf import settings
from django.core import mail

from olympia.abuse.models import AbuseReport
from olympia.amo.tests import TestCase


class TestAbuse(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_user(self):
        report = AbuseReport(user_id=999)
        report.send()
        assert (
            unicode(report) ==
            u'[User] Abuse Report for regularuser التطب')
        assert (
            mail.outbox[0].subject ==
            u'[User] Abuse Report for regularuser التطب')

        assert mail.outbox[0].to == [settings.ABUSE_EMAIL]

    def test_addon(self):
        report = AbuseReport(addon_id=3615)
        assert (
            unicode(report) ==
            u'[Extension] Abuse Report for Delicious Bookmarks')
        report.send()
        assert (
            mail.outbox[0].subject ==
            u'[Extension] Abuse Report for Delicious Bookmarks')

    def test_addon_fr(self):
        with self.activate(locale='fr'):
            report = AbuseReport(addon_id=3615)
            assert (
                unicode(report) ==
                u'[Extension] Abuse Report for Delicious Bookmarks')
            report.send()
        assert (
            mail.outbox[0].subject ==
            u'[Extension] Abuse Report for Delicious Bookmarks')
