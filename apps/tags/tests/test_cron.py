from nose.tools import eq_

import amo.tests
from addons.models import Addon
from files.models import File
from tags.models import Tag, AddonTag
from tags import cron


class TestTagJetpacks(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615']

    def setUp(self):
        Tag.objects.create(tag_text='jetpack')
        Tag.objects.create(tag_text='restartless')
        AddonTag.objects.all().delete()
        self.addon = Addon.objects.get(id=3615)

    def test_jetpack(self):
        File.objects.update(jetpack_version='1.0')
        cron.tag_jetpacks()
        eq_(['jetpack'], [t.tag_text for t in self.addon.tags.all()])

    def test_restartless(self):
        File.objects.update(no_restart=True)
        cron.tag_jetpacks()
        eq_(['restartless'], [t.tag_text for t in self.addon.tags.all()])

    def test_no_change(self):
        File.objects.update(no_restart=False, jetpack_version=None)
        cron.tag_jetpacks()
        eq_([], [t.tag_text for t in self.addon.tags.all()])

    def test_reverse(self):
        File.objects.update(no_restart=True, jetpack_version='1.0')
        cron.tag_jetpacks()
        eq_(['jetpack', 'restartless'],
            sorted([t.tag_text for t in self.addon.tags.all()]))

        File.objects.update(no_restart=False, jetpack_version=None)
        cron.tag_jetpacks()
        eq_([], [t.tag_text for t in self.addon.tags.all()])
