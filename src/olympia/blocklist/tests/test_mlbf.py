import json
import os
import tempfile

from filtercascade import FilterCascade

from olympia import amo
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.blocklist.models import Block
from olympia.blocklist.mlbf import MLBF
from olympia.files.models import File


class TestMLBF(TestCase):

    def setUp(self):
        for idx in range(0, 10):
            addon_factory()
        # one version, 0 - *
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        # one version, 0 - 9999
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            max_version='9999')
        # one version, 0 - *, unlisted
        Block.objects.create(
            addon=addon_factory(
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        # five versions, but only two within block (123.40, 123.5)
        self.five_ver = Block.objects.create(
            addon=addon_factory(
                version_kw={'version': '123.40'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(), max_version='123.45')
        self.five_ver_123_45 = self.five_ver.addon.current_version
        self.five_ver_123_5 = version_factory(
            addon=self.five_ver.addon, version='123.5', deleted=True,
            file_kw={'is_signed': True, 'is_webextension': True})
        self.five_ver_123_45_1 = version_factory(
            addon=self.five_ver.addon, version='123.45.1',
            file_kw={'is_signed': True, 'is_webextension': True})
        # these two would be included if they were signed and webextensions
        self.not_signed_version = version_factory(
            addon=self.five_ver.addon, version='123.5.1',
            file_kw={'is_signed': False, 'is_webextension': True})
        self.not_webext_version = version_factory(
            addon=self.five_ver.addon, version='123.5.2',
            file_kw={'is_signed': True, 'is_webextension': False})
        # no matching versions (edge cases)
        self.over = Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            max_version='0')
        self.under = Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            min_version='9999')

    def test_all_guids(self):
        all_guids = MLBF.get_all_guids()
        assert len(all_guids) == File.objects.count() == 10 + 10
        assert (self.five_ver.guid, '123.40') in all_guids
        assert (self.five_ver.guid, '123.5') in all_guids
        assert (self.five_ver.guid, '123.45.1') in all_guids
        assert (self.five_ver.guid, '123.5.1') in all_guids
        assert (self.five_ver.guid, '123.5.2') in all_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_guids
        assert under_tuple in all_guids

        # repeat, but with excluded version ids
        excludes = [self.five_ver_123_45.id, self.five_ver_123_5.id]
        all_guids = MLBF.get_all_guids(excludes)
        assert len(all_guids) == 18
        assert (self.five_ver.guid, '123.40') not in all_guids
        assert (self.five_ver.guid, '123.5') not in all_guids
        assert (self.five_ver.guid, '123.45.1') in all_guids
        assert (self.five_ver.guid, '123.5.1') in all_guids
        assert (self.five_ver.guid, '123.5.2') in all_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_guids
        assert under_tuple in all_guids

    def test_get_blocked_versions(self):
        blocked_versions = MLBF.get_blocked_versions()
        blocked_guids = blocked_versions.values()
        assert len(blocked_guids) == 5, blocked_guids
        assert (self.five_ver.guid, '123.40') in blocked_guids
        assert (self.five_ver.guid, '123.5') in blocked_guids
        assert (self.five_ver.guid, '123.45.1') not in blocked_guids
        assert (self.five_ver.guid, '123.5.1') not in blocked_guids
        assert (self.five_ver.guid, '123.5.2') not in blocked_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple not in blocked_guids
        assert under_tuple not in blocked_guids

        assert self.five_ver_123_45.id in blocked_versions
        assert self.five_ver_123_5.id in blocked_versions
        assert self.five_ver_123_45_1.id not in blocked_versions
        assert self.not_signed_version.id not in blocked_versions
        assert self.not_webext_version.id not in blocked_versions
        assert self.over.addon.current_version.id not in blocked_versions
        assert self.under.addon.current_version.id not in blocked_versions

        # doublecheck if the versions were signed & webextensions they'd be in.
        self.not_signed_version.all_files[0].update(is_signed=True)
        self.not_webext_version.all_files[0].update(is_webextension=True)
        assert len(MLBF.get_blocked_versions()) == 7

    def test_hash_filter_inputs(self):
        data = [
            ('guid@', '1.0'),
            ('foo@baa', '999.223a'),
        ]
        assert MLBF.hash_filter_inputs(data) == [
            'guid@:1.0',
            'foo@baa:999.223a',
        ]

    def test_generate_mlbf(self):
        stats = {}
        key_format = MLBF.KEY_FORMAT
        blocked = [
            ('guid1@', '1.0'), ('@guid2', '1.0'), ('@guid2', '1.1'),
            ('guid3@', '0.01b1')]
        not_blocked = [
            ('guid10@', '1.0'), ('@guid20', '1.0'), ('@guid20', '1.1'),
            ('guid30@', '0.01b1'), ('guid100@', '1.0'), ('@guid200', '1.0'),
            ('@guid200', '1.1'), ('guid300@', '0.01b1')]
        bfilter = MLBF.generate_mlbf(
            stats,
            blocked=MLBF.hash_filter_inputs(blocked),
            not_blocked=MLBF.hash_filter_inputs(not_blocked))
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter
        assert stats['mlbf_version'] == 2
        assert stats['mlbf_layers'] == 1
        assert stats['mlbf_bits'] == 2160
        with tempfile.NamedTemporaryFile() as out:
            bfilter.tofile(out)
            assert os.stat(out.name).st_size == 300

    def test_generate_and_write_mlbf(self):
        mlbf = MLBF(123456)
        mlbf.generate_and_write_mlbf()

        with open(mlbf.filter_path, 'rb') as filter_file:
            buffer = filter_file.read()
            bfilter = FilterCascade.from_buf(buffer)

        assert bfilter.bitCount() == 3008
        blocked_versions = mlbf.get_blocked_versions()
        for guid, version_str in blocked_versions.values():
            key = mlbf.KEY_FORMAT.format(guid=guid, version=version_str)
            assert key in bfilter
        for guid, version_str in mlbf.get_all_guids(blocked_versions.keys()):
            key = mlbf.KEY_FORMAT.format(guid=guid, version=version_str)
            assert key not in bfilter
        assert os.stat(mlbf.filter_path).st_size == 406

    def test_generate_diffs(self):
        old_versions = [
            ('guid1@', '1.0'), ('@guid2', '1.0'), ('@guid2', '1.1'),
            ('guid3@', '0.01b1')]
        new_versions = [
            ('guid1@', '1.0'), ('guid3@', '0.01b1'), ('@guid2', '1.1'),
            ('new_guid@', '0.01b1'), ('new_guid@', '24')]
        extras, deletes = MLBF.generate_diffs(old_versions, new_versions)
        assert extras == {('new_guid@', '0.01b1'), ('new_guid@', '24')}
        assert deletes == {('@guid2', '1.0')}

    def test_write_stash(self):
        old_mlbf = MLBF('old')
        old_mlbf.generate_and_write_mlbf()
        new_mlbf = MLBF('new_no_change')
        new_mlbf.generate_and_write_mlbf()
        new_mlbf.write_stash('old')
        with open(new_mlbf.stash_path) as stash_file:
            assert json.load(stash_file) == {'blocked': [], 'unblocked': []}
        # add a new Block and delete one
        Block.objects.create(
            addon=addon_factory(
                guid='fooo@baaaa',
                version_kw={'version': '999'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        self.five_ver_123_5.delete(hard=True)
        newer_mlbf = MLBF('new_one_change')
        newer_mlbf.generate_and_write_mlbf()
        newer_mlbf.write_stash('new_no_change')
        with open(newer_mlbf.stash_path) as stash_file:
            assert json.load(stash_file) == {
                'blocked': ['fooo@baaaa:999'],
                'unblocked': [f'{self.five_ver.guid}:123.5']}
