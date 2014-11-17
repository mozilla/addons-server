# -*- coding: utf-8 -*-
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from applications.models import AppVersion
from constants.applications import APPS
from files.models import File
from landfill.version import generate_version
from versions.models import ApplicationsVersions, Version


class VersionsTests(amo.tests.TestCase):

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_versions_themes_generation(self):
        generate_version(self.addon)
        eq_(Version.objects.all().count(), 1)
        eq_(File.objects.all().count(), 1)
        eq_(AppVersion.objects.all().count(), 0)
        eq_(ApplicationsVersions.objects.all().count(), 0)

    def test_versions_addons_generation(self):
        generate_version(self.addon, APPS['android'])
        eq_(Version.objects.all().count(), 1)
        eq_(File.objects.all().count(), 1)
        eq_(AppVersion.objects.all().count(), 2)
        eq_(ApplicationsVersions.objects.all().count(), 1)
