from datetime import datetime, timedelta

from django.conf import settings

from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.amo.tests import TestCase, user_factory
from olympia.devhub.serializers import DeveloperAgreementSerializer
from olympia.zadmin.models import set_config


class TestDeveloperAgreementSerializer(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.request.user = user_factory(display_name=None)
        self.change_date = datetime(2025, 8, 4, 0, 0)
        set_config(
            amo.config_keys.LAST_DEV_AGREEMENT_CHANGE_DATE,
            self.change_date.isoformat(),
        )
        self.serializer = DeveloperAgreementSerializer(
            context={'request': self.request}
        )

    def test_validate_last_developer_agreement_change(self):
        # Passes when matches agreement change date.
        assert (
            self.serializer.validate_last_developer_agreement_change(self.change_date)
            == self.change_date
        )

        # Errors on mismatch.
        with self.assertRaises(serializers.ValidationError):
            self.serializer.validate_last_developer_agreement_change(
                self.change_date + timedelta(days=1)
            )

        # When none is configured, uses the fallback.
        set_config(amo.config_keys.LAST_DEV_AGREEMENT_CHANGE_DATE, None)
        assert (
            self.serializer.validate_last_developer_agreement_change(
                settings.DEV_AGREEMENT_CHANGE_FALLBACK
            )
            == settings.DEV_AGREEMENT_CHANGE_FALLBACK
        )

        # Or, if the configured date is in the future, still uses the fallback.
        set_config(
            amo.config_keys.LAST_DEV_AGREEMENT_CHANGE_DATE,
            (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M'),
        )
        assert (
            self.serializer.validate_last_developer_agreement_change(
                settings.DEV_AGREEMENT_CHANGE_FALLBACK
            )
            == settings.DEV_AGREEMENT_CHANGE_FALLBACK
        )

    def _serializer(self, **data):
        data['last_developer_agreement_change'] = self.change_date.isoformat()
        return DeveloperAgreementSerializer(
            data=data, context={'request': self.request}
        )

    def test_validate_display_name_required_for_anonymous_user(self):
        assert self.request.user.has_anonymous_display_name
        serializer = self._serializer()
        assert not serializer.is_valid()
        assert serializer.errors['display_name'] == ['display_name is required.']

    def test_validate_display_name_rejected_when_user_already_has_one(self):
        self.request.user.update(display_name='user')
        serializer = self._serializer(display_name='newuser')
        assert not serializer.is_valid()
        assert serializer.errors['display_name'] == ['User already has display_name.']

    def test_valid_when_user_already_has_display_name_and_field_omitted(self):
        self.request.user.update(display_name='user')
        serializer = self._serializer()
        assert serializer.is_valid(), serializer.errors
        assert 'display_name' not in serializer.validated_data
