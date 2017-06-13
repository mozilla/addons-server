# -*- coding: utf-8 -*-
from django.core.urlresolvers import reverse

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.abuse.models import AbuseReport
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
        AbuseReport.objects.create(user=user_factory(), message='Eheheheh')

        url = reverse('admin:abuse_abusereport_changelist')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3

        response = self.client.get(url, {'type': 'addon'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 2

        response = self.client.get(url, {'type': 'user'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
