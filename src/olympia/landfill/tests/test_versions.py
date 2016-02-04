# -*- coding: utf-8 -*-
from nose.tools import eq_

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.applications.models import AppVersion
from olympia.constants.applications import APPS
from olympia.files.models import File
from olympia.landfill.version import generate_version
from olympia.versions.models import ApplicationsVersions, Version


class VersionsTests(TestCase):

    def setUp(self):
        super(VersionsTests, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_versions_themes_generation(self):
        num_appversions = AppVersion.objects.all().count()
        generate_version(self.addon)
        eq_(Version.objects.all().count(), 1)
        eq_(File.objects.all().count(), 1)
        eq_(AppVersion.objects.all().count(), num_appversions)
        eq_(ApplicationsVersions.objects.all().count(), 0)

    def test_versions_addons_generation(self):
        num_appversions = AppVersion.objects.all().count()
        generate_version(self.addon, APPS['android'])
        eq_(Version.objects.all().count(), 1)
        eq_(File.objects.all().count(), 1)
        eq_(AppVersion.objects.all().count(), num_appversions + 2)
        eq_(ApplicationsVersions.objects.all().count(), 1)
