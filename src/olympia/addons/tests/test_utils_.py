# -*- coding: utf-8 -*-
from unittest import mock
import pytest

from django.conf import settings
from django.forms import ValidationError

from olympia.addons.utils import (
    get_addon_recommendations,
    get_addon_recommendations_invalid,
    is_outcome_recommended,
    TAAR_LITE_FALLBACK_REASON_EMPTY,
    TAAR_LITE_FALLBACK_REASON_TIMEOUT,
    TAAR_LITE_FALLBACKS,
    TAAR_LITE_OUTCOME_CURATED,
    TAAR_LITE_OUTCOME_REAL_FAIL,
    TAAR_LITE_OUTCOME_REAL_SUCCESS,
    TAAR_LITE_FALLBACK_REASON_INVALID,
    verify_mozilla_trademark,
)
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.users.models import Group, GroupUser


@pytest.mark.django_db
@pytest.mark.parametrize(
    'name, allowed, give_permission',
    (
        ('Fancy new Add-on', True, False),
        # We allow the 'for ...' postfix to be used
        ('Fancy new Add-on for Firefox', True, False),
        ('Fancy new Add-on for Mozilla', True, False),
        # But only the postfix
        ('Fancy new Add-on for Firefox Browser', False, False),
        ('For Firefox fancy new add-on', False, False),
        # But users with the TRADEMARK_BYPASS permission are allowed
        ('Firefox makes everything better', False, False),
        ('Firefox makes everything better', True, True),
        ('Mozilla makes everything better', True, True),
        # A few more test-cases...
        ('Firefox add-on for Firefox', False, False),
        ('Firefox add-on for Firefox', True, True),
        ('Foobarfor Firefox', False, False),
        ('Better Privacy for Firefox!', True, False),
        ('Firefox awesome for Mozilla', False, False),
        ('Firefox awesome for Mozilla', True, True),
    ),
)
def test_verify_mozilla_trademark(name, allowed, give_permission):
    user = user_factory()
    if give_permission:
        group = Group.objects.create(name=name, rules='Trademark:Bypass')
        GroupUser.objects.create(group=group, user=user)

    if not allowed:
        with pytest.raises(ValidationError) as exc:
            verify_mozilla_trademark(name, user)
        assert exc.value.message == (
            'Add-on names cannot contain the Mozilla or Firefox trademarks.'
        )
    else:
        verify_mozilla_trademark(name, user)


class TestGetAddonRecommendations(TestCase):
    def setUp(self):
        patcher = mock.patch('olympia.addons.utils.call_recommendation_server')
        self.recommendation_server_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.a101 = addon_factory(id=101, guid='101@mozilla')
        addon_factory(id=102, guid='102@mozilla')
        addon_factory(id=103, guid='103@mozilla')
        addon_factory(id=104, guid='104@mozilla')

        self.recommendation_guids = [
            '101@mozilla',
            '102@mozilla',
            '103@mozilla',
            '104@mozilla',
        ]
        self.recommendation_server_mock.return_value = self.recommendation_guids

    def test_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == self.recommendation_guids
        assert outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS
        assert reason is None
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_recommended_no_results(self):
        self.recommendation_server_mock.return_value = []
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_EMPTY
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_recommended_timeout(self):
        self.recommendation_server_mock.return_value = None
        recommendations, outcome, reason = get_addon_recommendations('a@b', True)
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason is TAAR_LITE_FALLBACK_REASON_TIMEOUT
        self.recommendation_server_mock.assert_called_with(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, 'a@b', {}
        )

    def test_not_recommended(self):
        recommendations, outcome, reason = get_addon_recommendations('a@b', False)
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_CURATED
        assert reason is None

    def test_invalid_fallback(self):
        recommendations, outcome, reason = get_addon_recommendations_invalid()
        assert not self.recommendation_server_mock.called
        assert recommendations == TAAR_LITE_FALLBACKS
        assert outcome == TAAR_LITE_OUTCOME_REAL_FAIL
        assert reason == TAAR_LITE_FALLBACK_REASON_INVALID

    def test_is_outcome_recommended(self):
        assert is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_SUCCESS)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_REAL_FAIL)
        assert not is_outcome_recommended(TAAR_LITE_OUTCOME_CURATED)
        assert not self.recommendation_server_mock.called
