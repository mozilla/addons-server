from olympia.amo.tests import TestCase

from ..enum import EnumChoices, EnumChoicesApiDash, StrEnumChoices


class TestStrEnumChoices(TestCase):
    klass = StrEnumChoices

    def test_subset(self):
        class Choices(self.klass):
            FIRST = 'first', 'First Choice'
            SECOND = 'second', 'Second Choice'
            THIRD = 'third', 'Third Choice'

        Choices.add_subset('FIRST_AND_SECOND', ['FIRST', 'SECOND'])

        assert hasattr(Choices, 'FIRST_AND_SECOND')
        assert isinstance(Choices.FIRST_AND_SECOND, Choices.__class__)
        assert 'FIRST_AND_SECOND' not in Choices

        assert len(Choices.FIRST_AND_SECOND) == 2
        assert Choices.FIRST_AND_SECOND.FIRST.value == 'first'
        assert Choices.FIRST_AND_SECOND.FIRST.label == 'First Choice'
        assert Choices.FIRST_AND_SECOND.SECOND.value == 'second'
        assert Choices.FIRST_AND_SECOND.SECOND.label == 'Second Choice'

        subset = Choices.extract_subset('THIRD', 'FIRST')
        assert len(subset) == 2
        assert subset.THIRD.value == 'third'
        assert subset.THIRD.label == 'Third Choice'
        assert subset.FIRST.value == 'first'
        assert subset.FIRST.label == 'First Choice'
        assert subset.__name__ == 'ChoicesSubset'
        assert not hasattr(Choices, 'ChoicesSubset')
        # the subset is still an EnumChoices, with the same functions
        assert subset.extract_subset('THIRD').THIRD.value == 'third'

    def test_choices_with_none(self):
        class Choices(self.klass):
            NO_DECISION = 'no', 'No decision'
            AMO_BAN_USER = 'ban', 'User ban'

            __empty__ = 'None'

        assert Choices.choices == [
            (None, 'None'),
            ('no', 'No decision'),
            ('ban', 'User ban'),
        ]

    def test_api_values(self):
        class Choices(self.klass):
            NO_DECISION = 'no', 'No decision'
            AMO_BAN_USER = 'ban', 'User ban'

            __empty__ = 'None'

        assert Choices.NO_DECISION.api_value == 'no_decision'
        assert Choices.AMO_BAN_USER.api_value == 'amo_ban_user'
        assert Choices.api_values == ['no_decision', 'amo_ban_user']
        assert Choices.api_choices == [
            (None, None),
            ('no', 'no_decision'),
            ('ban', 'amo_ban_user'),
        ]

        assert Choices(Choices.NO_DECISION.value).api_value == 'no_decision'
        assert Choices[Choices.NO_DECISION.name].api_value == 'no_decision'

        assert (
            Choices.extract_subset('NO_DECISION').NO_DECISION.api_value == 'no_decision'
        )


class TestEnumChoices(TestCase):
    klass = EnumChoices

    def test_subset(self):
        class Choices(self.klass):
            FIRST = 1, 'First Choice'
            SECOND = 2, 'Second Choice'
            THIRD = 3, 'Third Choice'

        Choices.add_subset('FIRST_AND_SECOND', ['FIRST', 'SECOND'])

        assert hasattr(Choices, 'FIRST_AND_SECOND')
        assert isinstance(Choices.FIRST_AND_SECOND, Choices.__class__)
        assert 'FIRST_AND_SECOND' not in Choices

        assert len(Choices.FIRST_AND_SECOND) == 2
        assert Choices.FIRST_AND_SECOND.FIRST.value == 1
        assert Choices.FIRST_AND_SECOND.FIRST.label == 'First Choice'
        assert Choices.FIRST_AND_SECOND.SECOND.value == 2
        assert Choices.FIRST_AND_SECOND.SECOND.label == 'Second Choice'

        subset = Choices.extract_subset('THIRD', 'FIRST')
        assert len(subset) == 2
        assert subset.THIRD.value == 3
        assert subset.THIRD.label == 'Third Choice'
        assert subset.FIRST.value == 1
        assert subset.FIRST.label == 'First Choice'
        assert subset.__name__ == 'ChoicesSubset'
        assert not hasattr(Choices, 'ChoicesSubset')
        # the subset is still an EnumChoices, with the same functions
        assert subset.extract_subset('THIRD').THIRD.value == 3

    def test_choices_with_none(self):
        class Choices(self.klass):
            NO_DECISION = 0, 'No decision'
            AMO_BAN_USER = 1, 'User ban'

            __empty__ = 'None'

        assert Choices.choices == [
            (None, 'None'),
            (0, 'No decision'),
            (1, 'User ban'),
        ]

    def test_api_values(self):
        class Choices(self.klass):
            NO_DECISION = 0, 'No decision'
            AMO_BAN_USER = 1, 'User ban'

            __empty__ = 'None'

        assert Choices.NO_DECISION.api_value == 'no_decision'
        assert Choices.AMO_BAN_USER.api_value == 'amo_ban_user'
        assert Choices.api_values == ['no_decision', 'amo_ban_user']
        assert Choices.api_choices == [
            (None, None),
            (0, 'no_decision'),
            (1, 'amo_ban_user'),
        ]

        assert Choices(Choices.NO_DECISION.value).api_value == 'no_decision'
        assert Choices[Choices.NO_DECISION.name].api_value == 'no_decision'

        assert (
            Choices.extract_subset('NO_DECISION').NO_DECISION.api_value == 'no_decision'
        )


class TestEnumChoicesApiDash(TestEnumChoices):
    klass = EnumChoicesApiDash

    def test_api_values(self):
        class Choices(self.klass):
            NO_DECISION = 0, 'No decision'
            AMO_BAN_USER = 1, 'User ban'

            __empty__ = 'None'

        assert Choices.NO_DECISION.api_value == 'no-decision'
        assert Choices.AMO_BAN_USER.api_value == 'amo-ban-user'
        assert Choices.api_values == ['no-decision', 'amo-ban-user']
        assert Choices.api_choices == [
            (None, None),
            (0, 'no-decision'),
            (1, 'amo-ban-user'),
        ]

        assert Choices(Choices.NO_DECISION.value).api_value == 'no-decision'
        assert Choices[Choices.NO_DECISION.name].api_value == 'no-decision'

        assert Choices.from_api_value('no-decision') == Choices.NO_DECISION

        assert (
            Choices.extract_subset('NO_DECISION').NO_DECISION.api_value == 'no-decision'
        )
