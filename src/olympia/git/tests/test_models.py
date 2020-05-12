from olympia.amo.tests import TestCase, addon_factory
from olympia.git.models import GitExtractionEntry


class TestGitExtractionEntry(TestCase):
    def test_string_representation(self):
        addon = addon_factory()
        entry = GitExtractionEntry(addon=addon)

        assert str(entry) == 'Entry for "{}" (in_progress={})'.format(
            str(addon), entry.in_progress
        )

        entry.in_progress = True
        assert '(in_progress=True)' in str(entry)

        entry.in_progress = False
        assert '(in_progress=False)' in str(entry)
