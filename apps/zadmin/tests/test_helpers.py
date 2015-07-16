# -*- coding: utf-8 -*-
import itertools
from collections import defaultdict

from django.conf import settings

from mock import Mock, patch
from nose.tools import eq_

import amo.tests
from addons.models import Addon, AddonUser
from abuse.models import AbuseReport
from amo.helpers import absolutify
from amo.urlresolvers import resolve, reverse
from bandwagon.models import (Collection, CollectionAddon, CollectionUser,
                              CollectionVote, CollectionWatcher)
from files.models import File, FileUpload
from reviews.models import Review
from users.models import UserProfile
from versions.models import Version
from zadmin.helpers import MassDeleteHelper

from zadmin.helpers import MassDeleteHelper

class MassDeletionTest(amo.tests.TestCase):
    fixtures = ['addons/featured',
                'base/featured',
                'base/collections',
                'base/users',
                'base/addon_3615',
                'base/addon_3723_listed',
                'reviews/test_models',
                'bandwagon/featured_collections']

    OBJECTS = (
        {'model': UserProfile, 'pk': 999, 'related': {}},
        {
            'model': UserProfile,
            'pk': 10482,
            'related': {
                Collection: [80, 56445, 56446, 56447],
            }
        },
        {'model': Collection, 'pk': 80, 'related': {}},
        {'model': Collection, 'pk': 56445, 'related': {}},
        {
            'model': Addon,
            'pk': 4,
            'related': {
                Review: [1, 2],
                File: [592],
                Version: [5, 592],
            }
        },
        {
            'model': Addon,
            'pk': 3615,
            'related': {
                AddonUser: [2818],
                CollectionAddon: [207981],
                File: [67442],
                Version: [81551],
            }
        },
        {
            'model': Addon,
            'pk': 3723,
            'related': {
                AddonUser: [2905],
                Version: [89774],
            }
        },
        {'model': Review, 'pk': 1, 'related': {}},
        {'model': Review, 'pk': 2, 'related': {}},
    )

    def setUp(self):
        self.objects = defaultdict(list)
        for obj in self.OBJECTS:
            model = obj['model']
            self.objects[model.__name__].append(
                model.objects.get(pk=obj['pk']))

        self.objects = dict(self.objects)

        self.urls = tuple(o.get_url_path()
                          for objs in self.objects.values()
                          for o in objs)

        self.fake_urls = (
            'https://addons.mozilla.org/en-US/firefox/addon/floorgl-plikzret/',
            '/foo/bar/zuq/',
        )

    def assert_deleted(self):
        for obj in self.OBJECTS:
            assert not obj['model'].objects.filter(pk=obj['pk']).exists()

            for model, pks in obj['related'].iteritems():
                assert not model.objects.filter(pk__in=pks).exists()


class TestMassDeletion(MassDeletionTest):
    def test_relative_vs_absolute_urls(self):
        helper1 = MassDeleteHelper(urls=self.urls)
        helper2 = MassDeleteHelper(urls=map(absolutify, self.urls))

        eq_(helper1.object_types_json,
            helper2.object_types_json)

    def test_url_resolution(self):
        helper1 = MassDeleteHelper(urls=self.urls + self.fake_urls)
        helper2 = MassDeleteHelper(objects=self.objects)

        eq_(helper1.unknown_urls, self.fake_urls)

        eq_(helper1.object_types_json,
            helper2.object_types_json)

        eq_(helper1.object_types,
            self.objects)

    def test_related_objects(self):
        helper = MassDeleteHelper(objects=self.objects)
        for obj in self.OBJECTS:
            model = obj['model']
            related = dict((k, set(v))
                           for k, v in obj['related'].iteritems())

            for model, objs in helper.get_related_objects(model, [obj['pk']]):
                for o in objs:
                    assert model in related
                    assert o.pk in related[model]

                    related[model].remove(o.pk)

            assert not any(related.values())

    def test_deletion(self):
        helper = MassDeleteHelper(objects=self.objects)
        helper.delete_objects()

        self.assert_deleted()

