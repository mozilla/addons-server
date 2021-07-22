from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.tags.models import AddonTag, Tag


class TestCount(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5369', 'tags/tags.json']
    exempt_from_fixture_bundling = True

    def setUp(self):
        self.tag = Tag.objects.get(pk=2652)

    def test_count(self):
        self.tag.update_stat()
        assert self.tag.num_addons == 1

    def test_add_tag(self):
        self.tag.add_tag(addon=Addon.objects.get(pk=5369))
        assert self.tag.reload().num_addons == 2

    def test_remove_tag(self):
        self.tag.remove_tag(addon=Addon.objects.get(pk=3615))
        assert self.tag.reload().num_addons == 0

    def test_add_addontag(self):
        AddonTag.objects.create(addon_id=5369, tag_id=self.tag.pk)
        assert self.tag.reload().num_addons == 2

    def test_delete_addontag(self):
        addontag = AddonTag.objects.all()[0]
        tag = addontag.tag
        tag.update_stat()
        assert tag.reload().num_addons == 1
        addontag.delete()
        assert tag.reload().num_addons == 0

    def test_delete_tag(self):
        pk = self.tag.pk
        self.tag.update_stat()
        self.tag.delete()
        assert Tag.objects.filter(pk=pk).count() == 0
