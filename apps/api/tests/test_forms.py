# -*- coding: utf-8 -*-
import json

from nose.tools import eq_

from amo.tests import TestCase
from api.forms import ChecksumsForm
from devhub.tasks import get_libraries


class ChecksumsFormTest(TestCase):

    def _form(self, data):
        return ChecksumsForm({'checksum_json': json.dumps(data)})

    def _library_form(self, **kw):
        return self._form({'frameworks': {},
                           'libraries': {
                               'lib-id': kw},
                           'hashes': {}})

    def _version_form(self, **kw):
        version = {'files': {}}
        version.update(kw)
        return self._library_form(versions={'1.0': version})

    def _hash_form(self, **kw):
        hash = kw.pop('hash',
                      'a2c064616af4c66c576821616646bdfa'
                      'd5556a263b4b007847605118971f4389')

        hashes = {hash: {
            'sources': [
                ['library', 'version', 'path']]}}
        hashes[hash].update(kw)

        return self._form({
            'libraries': {},
            'frameworks': {},
            'hashes': hashes})

    def test_stock_validation(self):
        """Test that stock checksums JSON passes validation."""

        eq_(self._form(get_libraries()).errors, {})

    def test_skeleton_library(self):
        """Tests that a skeleton library passes validation."""

        eq_(self._library_form().errors, {})
        eq_(self._version_form().errors, {})

    def test_fail_invalid_messages(self):
        """Tests that invalid messages data causes failure."""

        for thing in 'foo', {}, 42, True, None:
            assert not self._library_form(messages=thing).is_valid()
            assert not self._version_form(messages=thing).is_valid()
            assert not self._hash_form(messages=thing).is_valid()

        for thing in {}, 42, True, None:
            assert not self._library_form(messages=[thing]).is_valid()
            assert not self._version_form(messages=[thing]).is_valid()
            assert not self._hash_form(messages=[thing]).is_valid()

        assert self._library_form(messages=['foo', 'bar']).is_valid()
        assert self._version_form(messages=['foo', 'bar']).is_valid()
        assert self._hash_form(messages=['foo', 'bar']).is_valid()

    def test_missing_sections(self):
        """Tests that data with missing sections fails."""

        sections = 'frameworks', 'libraries', 'hashes'
        data = dict((sect, {}) for sect in sections)

        eq_(self._form(data).errors, {})

        for sect in sections:
            d = data.copy()
            del d[sect]
            assert not self._form(d).is_valid()

            for thing in [], 'foo', 42, True:
                d = data.copy()
                d[sect] = thing
                assert not self._form(d).is_valid()

    def test_invalid_hashes(self):
        """Tests that invalid hashes are not accepted."""

        eq_(self._hash_form().errors, {})

        assert not self._hash_form(hash='foo').is_valid()

        for thing in {}, 'foo', 42, True:
            assert not self._hash_form(sources=thing).is_valid()
            assert not self._hash_form(sources=[thing]).is_valid()

        for thing in {}, 42, True:
            assert not (self._hash_form(sources=[[thing, thing, thing]])
                        .is_valid())
