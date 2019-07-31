from olympia.amo.tests import TestCase, addon_factory

from olympia.files.models import FileUpload
from olympia.yara.models import YaraResult


class TestYaraResult(TestCase):
    def test_create(self):
        addon = addon_factory()
        upload = FileUpload.objects.create(addon=addon)

        r = YaraResult.objects.create(upload=upload)

        assert r.id is not None
        assert r.upload == upload
        assert r.matches == []
        assert r.version is None

    def test_add_match(self):
        addon = addon_factory()
        upload = FileUpload.objects.create(addon=addon)
        r = YaraResult.objects.create(upload=upload)

        rule = 'some-yara-rule'
        tags = ['foo']
        meta = {'description': 'some description for some-yara-rule'}
        r.add_match(rule=rule, tags=tags, meta=meta)

        assert r.matches == [{
            'rule': rule,
            'tags': tags,
            'meta': meta,
        }]
