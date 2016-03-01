# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.addons.models import (
    Addon, attach_categories, attach_tags, attach_translations)
from olympia.addons.search import extract


class TestExtract(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestExtract, self).setUp()
        self.attrs = (
            'id', 'slug', 'created', 'default_locale', 'last_updated',
            'weekly_downloads', 'average_daily_users', 'status', 'type',
            'hotness', 'is_disabled', 'is_listed',
        )
        self.transforms = (attach_categories, attach_tags, attach_translations)

    def _extract(self):
        qs = Addon.objects.filter(id__in=[3615])
        for t in self.transforms:
            qs = qs.transform(t)
        self.addon = list(qs)[0]
        return extract(self.addon)

    def test_extract_attributes(self):
        extracted = self._extract()
        for attr in self.attrs:
            assert extracted[attr] == getattr(self.addon, attr)

    def test_extract_translations(self):
        translations_name = {
            'en-US': u'Name in ënglish',
            'es': u'Name in Español',
            'it': None,  # Empty name should be ignored in extract.
        }
        translations_description = {
            'en-US': u'Description in ënglish',
            'es': u'Description in Español',
            'fr': '',  # Empty description should be ignored in extract.
        }
        self.addon = Addon.objects.get(pk=3615)
        self.addon.name = translations_name
        self.addon.description = translations_description
        self.addon.save()
        extracted = self._extract()
        assert extracted['name_translations'] == [
            {'lang': u'en-US', 'string': translations_name['en-US']},
            {'lang': u'es', 'string': translations_name['es']},
        ]
        assert extracted['description_translations'] == [
            {'lang': u'en-US', 'string': translations_description['en-US']},
            {'lang': u'es', 'string': translations_description['es']},
        ]
