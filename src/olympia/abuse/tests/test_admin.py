# -*- coding: utf-8 -*-
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.abuse.models import AbuseReport
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, user_factory
from olympia.users.models import UserProfile


class TestAbuse(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_list(self):
        addon = Addon.objects.get(pk=3615)
        user = UserProfile.objects.get(pk=999)

        # Create a few abuse reports
        AbuseReport.objects.create(addon=addon, message='Foo')
        AbuseReport.objects.create(
            addon=addon, ip_address='1.2.3.4', reporter=user_factory(),
            message='Bar')
        # This is a report for an addon not in the database
        AbuseReport.objects.create(guid='@guid', message='Foo')
        AbuseReport.objects.create(user=user_factory(), message='Eheheheh')

        url = reverse('admin:abuse_abusereport_changelist')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 4

        response = self.client.get(url, {'type': 'addon'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3

        response = self.client.get(url, {'type': 'user'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
