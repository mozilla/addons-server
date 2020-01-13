from datetime import datetime, timedelta
from unittest import mock

import pytest

from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.constants.scanners import (
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    FLAG_FOR_HUMAN_REVIEW,
    NO_ACTION,
    YARA,
)
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.scanners.actions import (
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _flag_for_human_review,
    _no_action,
)


class TestActions(TestCase):
    def test_action_does_nothing(self):
        version = version_factory(addon=addon_factory())
        _no_action(version)

    def test_flags_a_version_for_human_review(self):
        version = version_factory(addon=addon_factory())
        assert not version.needs_human_review
        _flag_for_human_review(version)
        assert version.needs_human_review
        version.reload()
        assert version.needs_human_review

    def test_delay_auto_approval(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.needs_human_review
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval(version)
        self.assertCloseToNow(
            addon.auto_approval_delayed_until,
            now=datetime.now() + timedelta(hours=24),
        )
        assert version.needs_human_review

    def test_delay_auto_approval_indefinitely(self):
        addon = addon_factory()
        version = addon.current_version
        assert not version.needs_human_review
        assert addon.auto_approval_delayed_until is None
        _delay_auto_approval_indefinitely(version)
        assert addon.auto_approval_delayed_until == datetime.max
        assert version.needs_human_review


class TestRunAction(TestCase):
    def setUp(self):
        super(TestRunAction, self).setUp()

        self.scanner = YARA
        self.version = version_factory(addon=addon_factory())
        self.scanner_rule = ScannerRule.objects.create(
            name='rule-1', scanner=self.scanner, action=NO_ACTION
        )
        self.scanner_result = ScannerResult.objects.create(
            version=self.version, scanner=self.scanner
        )
        self.scanner_result.matched_rules.add(self.scanner_rule)

    @mock.patch('olympia.scanners.models._no_action')
    def test_runs_no_action(self, no_action_mock):
        self.scanner_rule.update(action=NO_ACTION)

        ScannerResult.run_action(self.version)

        assert no_action_mock.called
        no_action_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_runs_flag_for_human_review(self, flag_for_human_review_mock):
        self.scanner_rule.update(action=FLAG_FOR_HUMAN_REVIEW)

        ScannerResult.run_action(self.version)

        assert flag_for_human_review_mock.called
        flag_for_human_review_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.models._delay_auto_approval')
    def test_runs_delay_auto_approval(self, _delay_auto_approval_mock):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL)

        ScannerResult.run_action(self.version)

        assert _delay_auto_approval_mock.called
        _delay_auto_approval_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.models._delay_auto_approval_indefinitely')
    def test_runs_delay_auto_approval_indefinitely(
        self, _delay_auto_approval_indefinitely_mock
    ):
        self.scanner_rule.update(action=DELAY_AUTO_APPROVAL_INDEFINITELY)

        ScannerResult.run_action(self.version)

        assert _delay_auto_approval_indefinitely_mock.called
        _delay_auto_approval_indefinitely_mock.assert_called_with(self.version)

    @mock.patch('olympia.scanners.models.log.info')
    def test_returns_when_no_action_found(self, log_mock):
        self.scanner_rule.delete()

        ScannerResult.run_action(self.version)

        log_mock.assert_called_with(
            'No action to execute for version %s.', self.version.id
        )

    def test_raise_when_action_is_invalid(self):
        # `12345` is an invalid action ID
        self.scanner_rule.update(action=12345)

        with pytest.raises(Exception, match='invalid action 12345'):
            ScannerResult.run_action(self.version)

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_selects_the_action_with_the_highest_severity(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`.
        rule = ScannerRule.objects.create(
            name='rule-2', scanner=self.scanner, action=FLAG_FOR_HUMAN_REVIEW
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert not no_action_mock.called
        assert flag_for_human_review_mock.called

    @mock.patch('olympia.scanners.models._no_action')
    @mock.patch('olympia.scanners.models._flag_for_human_review')
    def test_selects_active_actions_only(
        self, flag_for_human_review_mock, no_action_mock
    ):
        # Create another rule and add it to the current scanner result. This
        # rule is more severe than `rule-1` created in `setUp()`. In this test
        # case, we disable this rule, though.
        rule = ScannerRule.objects.create(
            name='rule-2',
            scanner=self.scanner,
            action=FLAG_FOR_HUMAN_REVIEW,
            is_active=False,
        )
        self.scanner_result.matched_rules.add(rule)

        ScannerResult.run_action(self.version)

        assert no_action_mock.called
        assert not flag_for_human_review_mock.called
