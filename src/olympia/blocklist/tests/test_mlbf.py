import os
import tempfile

from olympia import amo
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.blocklist.models import Block
from olympia.blocklist.mlbf import (
    generate_mlbf, get_all_guids, get_blocked_guids, get_mlbf_key_format,
    hash_filter_inputs)
from olympia.files.models import File


class TestMLBF(TestCase):

    def setUp(self):
        for idx in range(0, 10):
            addon_factory()
        # one version, 0 - *
        Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory())
        # one version, 0 - 9999
        Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory(),
            max_version='9999')
        # one version, 0 - *, unlisted
        Block.objects.create(
            addon=addon_factory(
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED}),
            updated_by=user_factory())
        # three versions, but only two within block (123.40, 123.5)
        self.three_ver = Block.objects.create(
            addon=addon_factory(
                version_kw={'version': '123.40'}),
            updated_by=user_factory(), max_version='123.45')
        version_factory(
            addon=self.three_ver.addon, version='123.5')
        version_factory(
            addon=self.three_ver.addon, version='123.45.1')
        # no matching versions (edge cases)
        self.over = Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory(),
            max_version='0')
        self.under = Block.objects.create(
            addon=addon_factory(),
            updated_by=user_factory(),
            min_version='9999')

    def test_all_guids(self):
        all_guids = get_all_guids()
        assert len(all_guids) == File.objects.count() == 10 + 8
        assert (self.three_ver.guid, '123.40') in all_guids
        assert (self.three_ver.guid, '123.5') in all_guids
        assert (self.three_ver.guid, '123.45.1') in all_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_guids
        assert under_tuple in all_guids

    def test_get_blocked_guids(self):
        blocked_guids = get_blocked_guids()
        assert len(blocked_guids) == 5
        assert (self.three_ver.guid, '123.40') in blocked_guids
        assert (self.three_ver.guid, '123.5') in blocked_guids
        assert (self.three_ver.guid, '123.45.1') not in blocked_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple not in blocked_guids
        assert under_tuple not in blocked_guids

    def test_hash_filter_inputs(self):
        data = [
            ('guid@', '1.0'),
            ('foo@baa', '999.223a'),
        ]
        assert hash_filter_inputs(data, get_mlbf_key_format(37872)) == [
            '37872:guid@:1.0',
            '37872:foo@baa:999.223a',
        ]

    def test_generate_mlbf(self):
        stats = {}
        key_format = '{guid}:{version}'
        blocked = [
            ('guid1@', '1.0'), ('@guid2', '1.0'), ('@guid2', '1.1'),
            ('guid3@', '0.01b1')]
        not_blocked = [
            ('guid10@', '1.0'), ('@guid20', '1.0'), ('@guid20', '1.1'),
            ('guid30@', '0.01b1'), ('guid100@', '1.0'), ('@guid200', '1.0'),
            ('@guid200', '1.1'), ('guid300@', '0.01b1')]
        bfilter = generate_mlbf(
            stats, key_format, blocked=blocked, not_blocked=not_blocked)
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter
        assert stats['mlbf_version'] == 1
        assert stats['mlbf_layers'] == 2
        assert stats['mlbf_bits'] == 14409
        with tempfile.NamedTemporaryFile() as out:
            bfilter.tofile(out)
            assert os.stat(out.name).st_size == 1824
