# -*- coding: utf-8 -*-
from olympia.amo.tests import TestCase
from olympia.users.indexers import UserProfileIndexer
from olympia.users.models import UserProfile


class TestUserProfileIndexer(TestCase):
    def setUp(self):
        super(TestUserProfileIndexer, self).setUp()
        self.indexer = UserProfileIndexer()

    def _extract(self):
        # No transforms necessary as we don't care about translations atm.
        return self.indexer.extract_document(self.user)

    def test_extract_attributes(self):
        self.user = UserProfile.objects.create(
            email='nobody@mozilla.org', username='nobody',
            display_name=u'Nôbody', biography=u'My Bïo',
            homepage='http://example.com/', location=u'Nëverland',
            occupation='What')
        extracted = self._extract()
        for attr in ('email', 'username', 'display_name', 'biography',
                     'homepage', 'location', 'occupation'):
            assert extracted[attr] == unicode(getattr(self.user, attr))
        assert extracted['id'] == self.user.pk
        assert extracted['deleted'] == self.user.deleted

    def test_mapping(self):
        doc_name = self.indexer.get_doctype_name()
        assert doc_name

        mapping_properties = self.indexer.get_mapping()[doc_name]['properties']

        # Spot check: make sure addon-specific 'summary' field is not present.
        assert 'summary' not in mapping_properties

        # Make sure 'boost' is present.
        assert 'boost' in mapping_properties
