from olympia.amo.tests import TestCase
from olympia.translations.models import (
    PurifiedTranslation,
    Translation,
)


class TestTranslationCommands(TestCase):
    def setUp(self):
        # Create expected translations in 2 steps so that their autoid and id
        # are set as they would in production: first through .new() to create
        # the instance and "reserve" the id, then .save() to record everything
        # and generate an autoid (pk).
        self.translations = [
            # Translation that shouldn't be touched.
            Translation.new('<b>foo</b> bar', 'en-US'),
            # PurifiedTranslation that shouldn't be touched.
            PurifiedTranslation.new('<b>foo</b> bar', 'en-US'),
            # Translation that should be copied.
            Translation.new('<b>foo</b> bar', 'es'),
            # PurifiedTranslation that should be copied
            PurifiedTranslation.new('<b>foo</b> bar', 'es'),
        ]
        for translation in self.translations:
            translation.save()
