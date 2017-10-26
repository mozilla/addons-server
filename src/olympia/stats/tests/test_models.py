# -*- coding: utf-8 -*-
import json

from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.stats.models import Contribution
from olympia.stats.db import StatsDictField
from olympia.users.models import UserProfile


class TestStatsDictField(TestCase):

    def test_to_python_none(self):
        assert StatsDictField().to_python(None) is None

    def test_to_python_dict(self):
        assert StatsDictField().to_python({'a': 1}) == {'a': 1}

    def test_to_python_json(self):
        val = {'a': 1}
        assert StatsDictField().to_python(json.dumps(val)) == val


class TestEmail(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestEmail, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def make_contribution(self, amount, locale):
        return Contribution.objects.create(addon=self.addon, amount=amount,
                                           source_locale=locale)
