import json
import os
import tempfile
from unittest import mock

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
                version_kw={'version': '0.1'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            max_version='0')
        self.under = Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory(),
            min_version='9999')

    def test_fetch_all_versions_from_db(self):
        all_versions = MLBF.fetch_all_versions_from_db()
        assert len(all_versions) == File.objects.count() == 10 + 10
        assert (self.five_ver.guid, '123.40') in all_versions
        assert (self.five_ver.guid, '123.5') in all_versions
        assert (self.five_ver.guid, '123.45.1') in all_versions
        assert (self.five_ver.guid, '123.5.1') in all_versions
        assert (self.five_ver.guid, '123.5.2') in all_versions
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_versions
        assert under_tuple in all_versions

        # repeat, but with excluded version ids
        excludes = [self.five_ver_123_45.id, self.five_ver_123_5.id]
        all_versions = MLBF.fetch_all_versions_from_db(excludes)
        assert len(all_versions) == 18
        assert (self.five_ver.guid, '123.40') not in all_versions
        assert (self.five_ver.guid, '123.5') not in all_versions
        assert (self.five_ver.guid, '123.45.1') in all_versions
        assert (self.five_ver.guid, '123.5.1') in all_versions
        assert (self.five_ver.guid, '123.5.2') in all_versions
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_versions
        assert under_tuple in all_versions

    def test_fetch_blocked_from_db(self):
        blocked_versions = MLBF.fetch_blocked_from_db()
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
        assert len(MLBF.fetch_blocked_from_db()) == 7

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

    def test_generate_mlbf_with_more_blocked_than_not_blocked(self):
        key_format = MLBF.KEY_FORMAT
        blocked = [('guid1@', '1.0'), ('@guid2', '1.0')]
        not_blocked = [('guid10@', '1.0')]
        bfilter = MLBF.generate_mlbf(
            {},
            blocked=MLBF.hash_filter_inputs(blocked),
            not_blocked=MLBF.hash_filter_inputs(not_blocked))
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter

    def test_generate_and_write_mlbf(self):
        mlbf = MLBF(123456)
        mlbf.generate_and_write_mlbf()

        with open(mlbf.filter_path, 'rb') as filter_file:
            buffer = filter_file.read()
            bfilter = FilterCascade.from_buf(buffer)

        assert bfilter.bitCount() == 3008
        blocked_versions = mlbf.fetch_blocked_from_db()
        for guid, version_str in blocked_versions.values():
            key = mlbf.KEY_FORMAT.format(guid=guid, version=version_str)
            assert key in bfilter

        all_addons = mlbf.fetch_all_versions_from_db(blocked_versions.keys())
        for guid, version_str in all_addons:
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
        new_mlbf.write_stash(old_mlbf)
        empty_stash = {'blocked': [], 'unblocked': []}
        with open(new_mlbf._stash_path) as stash_file:
            assert json.load(stash_file) == empty_stash
        assert new_mlbf.stash_json == empty_stash
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
        newer_mlbf.write_stash(new_mlbf)
        full_stash = {
            'blocked': ['fooo@baaaa:999'],
            'unblocked': [f'{self.five_ver.guid}:123.5']}
        with open(newer_mlbf._stash_path) as stash_file:
            assert json.load(stash_file) == full_stash
        assert newer_mlbf.stash_json == full_stash

    def test_should_reset_base_filter_and_blocks_changed_since_previous(self):
        base_mlbf = MLBF('base')
        # should handle the files not existing
        assert MLBF('no_files').should_reset_base_filter(base_mlbf)
        assert MLBF('no_files').blocks_changed_since_previous(base_mlbf)
        base_mlbf.generate_and_write_mlbf()

        no_change_mlbf = MLBF('no_change')
        no_change_mlbf.generate_and_write_mlbf()
        assert not no_change_mlbf.should_reset_base_filter(base_mlbf)
        assert not no_change_mlbf.blocks_changed_since_previous(base_mlbf)

        # make some changes
        Block.objects.create(
            addon=addon_factory(
                guid='fooo@baaaa',
                version_kw={'version': '999'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        self.five_ver_123_5.delete(hard=True)
        small_change_mlbf = MLBF('small_change')
        small_change_mlbf.generate_and_write_mlbf()
        # but the changes were small (less than threshold) so no need for new
        # base filter
        assert not small_change_mlbf.should_reset_base_filter(base_mlbf)
        # there _were_ changes though
        assert small_change_mlbf.blocks_changed_since_previous(base_mlbf)
        # double check what the differences were
        diffs = MLBF.generate_diffs(
            previous=base_mlbf.blocked_json,
            current=small_change_mlbf.blocked_json)
        assert diffs == ({'fooo@baaaa:999'}, {f'{self.five_ver.guid}:123.5'})

        # so lower the threshold
        to_patch = 'olympia.blocklist.mlbf.MLBF.BASE_REPLACE_THRESHOLD'
        with mock.patch(to_patch, 1):
            assert small_change_mlbf.should_reset_base_filter(base_mlbf)
            assert small_change_mlbf.blocks_changed_since_previous(base_mlbf)
