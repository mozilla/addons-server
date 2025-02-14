from typing import TypedDict

from django.http import Http404
from django.utils.translation import gettext_lazy as _

import waffle
from rest_framework import serializers

import olympia.core.logger
from olympia import amo
from olympia.accounts.serializers import BaseUserSerializer
from olympia.api.exceptions import UnavailableForLegalReasons
from olympia.api.fields import ReverseChoiceField
from olympia.api.serializers import AMOModelSerializer
from olympia.bandwagon.serializers import CollectionSerializer
from olympia.constants.abuse import (
    ILLEGAL_CATEGORIES,
    ILLEGAL_SUBCATEGORIES,
    ILLEGAL_SUBCATEGORIES_BY_CATEGORY,
)

from .models import AbuseReport
from .tasks import report_to_cinder


log = olympia.core.logger.getLogger('z.abuse')


class BaseAbuseReportSerializer(AMOModelSerializer):
    error_messages = {
        'max_length': _(
            'Please ensure this field has no more than {max_length} characters.'
        )
    }

    reporter = BaseUserSerializer(read_only=True)
    reporter_email = serializers.EmailField(required=False, allow_null=True)
    reason = ReverseChoiceField(
        # Child classes may override the choices, but most only need
        # content-related reasons so we use that as the base.
        choices=list(AbuseReport.REASONS.CONTENT_REASONS.api_choices),
        required=False,
        allow_null=True,
    )
    # 'message' has custom validation rules below depending on whether 'reason'
    # was provided or not. We need to not set it as required and allow blank at
    # the field level to make that work.
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10000,
        error_messages=error_messages,
    )
    lang = serializers.CharField(
        required=False,
        source='application_locale',
        max_length=255,
        help_text=(
            'The language code of the locale used by the client for the application.'
        ),
    )
    illegal_category = ReverseChoiceField(
        choices=list(ILLEGAL_CATEGORIES.api_choices),
        required=False,
        allow_null=True,
    )
    illegal_subcategory = ReverseChoiceField(
        choices=list(ILLEGAL_SUBCATEGORIES.api_choices),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = AbuseReport
        fields = (
            'lang',
            'reason',
            'message',
            'reporter',
            'reporter_name',
            'reporter_email',
            'illegal_category',
            'illegal_subcategory',
        )

    def validate(self, data):
        if not data.get('reason'):
            # If reason is not provided, message is required and can not be
            # null or blank.
            message = data.get('message')
            if not message:
                if 'message' not in data:
                    msg = serializers.Field.default_error_messages['required']
                elif message is None:
                    msg = serializers.Field.default_error_messages['null']
                else:
                    msg = serializers.CharField.default_error_messages['blank']
                raise serializers.ValidationError({'message': [msg]})

        # When the reason is "illegal", the `illegal_category` field is
        # required.
        if data.get('reason') == AbuseReport.REASONS.ILLEGAL:
            if 'illegal_category' not in data:
                msg = serializers.Field.default_error_messages['required']
                raise serializers.ValidationError({'illegal_category': [msg]})
            elif data.get('illegal_category') is None:
                msg = serializers.Field.default_error_messages['null']
                raise serializers.ValidationError({'illegal_category': [msg]})
        elif data.get('illegal_category') is not None:
            msg = (
                'This value must be omitted or set to "null" when the `reason` is not '
                '"illegal".'
            )
            raise serializers.ValidationError({'illegal_category': [msg]})

        # When the reason is "illegal", the `illegal_subcategory` field is also
        # required. In addition, the subcategory depends on the category set.
        if data.get('reason') == AbuseReport.REASONS.ILLEGAL:
            subcategory = data.get('illegal_subcategory')
            valid_subcategories = ILLEGAL_SUBCATEGORIES_BY_CATEGORY.get(
                data.get('illegal_category'), []
            )
            if 'illegal_subcategory' not in data:
                msg = serializers.Field.default_error_messages['required']
                raise serializers.ValidationError({'illegal_subcategory': [msg]})
            elif subcategory is None:
                msg = serializers.Field.default_error_messages['null']
                raise serializers.ValidationError({'illegal_subcategory': [msg]})
            elif subcategory not in valid_subcategories:
                msg = (
                    'This value cannot be used in combination with the '
                    'supplied `illegal_category`.'
                )
                raise serializers.ValidationError({'illegal_subcategory': [msg]})
        elif data.get('illegal_subcategory') is not None:
            msg = (
                'This value must be omitted or set to "null" when the `reason` is not '
                '"illegal".'
            )
            raise serializers.ValidationError({'illegal_subcategory': [msg]})

        return data

    def validate_target(self, data, target_name):
        if target_name not in data:
            msg = serializers.Field.default_error_messages['required']
            raise serializers.ValidationError({target_name: [msg]})

    def to_internal_value(self, data):
        output = super().to_internal_value(data)
        request = self.context['request']
        output['country_code'] = request.META.get('HTTP_X_COUNTRY_CODE', '')
        if request.user.is_authenticated:
            output['reporter'] = request.user
        return output

    def create(self, validated_data):
        instance = super().create(validated_data)
        if (
            waffle.switch_is_active('dsa-job-technical-processing')
            and instance.is_individually_actionable
        ):
            # call task to fire off cinder report
            report_to_cinder.delay(instance.id)
        return instance


class AddonAbuseReportSerializer(BaseAbuseReportSerializer):
    class AddonDict(TypedDict):
        guid: str
        id: int | None
        slug: str | None

    addon = serializers.SerializerMethodField(
        help_text='The add-on reported for abuse.'
    )
    app = ReverseChoiceField(
        choices=list((v.id, k) for k, v in amo.APPS.items()),
        required=False,
        source='application',
    )
    appversion = serializers.CharField(
        required=False, source='application_version', max_length=255
    )
    report_entry_point = ReverseChoiceField(
        choices=list(AbuseReport.REPORT_ENTRY_POINTS.api_choices),
        required=False,
        allow_null=True,
    )
    addon_install_method = ReverseChoiceField(
        choices=list(AbuseReport.ADDON_INSTALL_METHODS.api_choices),
        required=False,
        allow_null=True,
    )
    addon_install_source = ReverseChoiceField(
        choices=list(AbuseReport.ADDON_INSTALL_SOURCES.api_choices),
        required=False,
        allow_null=True,
    )
    addon_signature = ReverseChoiceField(
        choices=list(AbuseReport.ADDON_SIGNATURES.api_choices),
        required=False,
        allow_null=True,
    )
    reason = ReverseChoiceField(
        # For add-ons we use the full list of reasons as choices.
        choices=list(AbuseReport.REASONS.api_choices),
        required=False,
        allow_null=True,
    )
    location = ReverseChoiceField(
        choices=list(AbuseReport.LOCATION.api_choices),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = AbuseReport
        fields = BaseAbuseReportSerializer.Meta.fields + (
            'addon',
            'addon_install_method',
            'addon_install_origin',
            'addon_install_source',
            'addon_install_source_url',
            'addon_name',
            'addon_signature',
            'addon_summary',
            'addon_version',
            'app',
            'appversion',
            'client_id',
            'install_date',
            'operating_system',
            'operating_system_version',
            'report_entry_point',
            'location',
        )

    def validate_client_id(self, value):
        if value and not amo.VALID_CLIENT_ID.match(str(value)):
            raise serializers.ValidationError(_('Invalid value'))
        return value

    def handle_unknown_install_method_or_source(self, data, field_name):
        reversed_choices = self.fields[field_name].reversed_choices
        value = data[field_name]

        try:
            is_value_unknown = value not in reversed_choices
        except TypeError as exc:
            # Log the invalid type and raise a validation error.
            log.warning(
                'Invalid type for abuse report %s value submitted: %s',
                field_name,
                str(data[field_name])[:255],
            )
            raise serializers.ValidationError({field_name: _('Invalid value')}) from exc

        if is_value_unknown:
            log.warning(
                'Unknown abuse report %s value submitted: %s',
                field_name,
                str(data[field_name])[:255],
            )
            value = 'other'
        return value

    def handle_addon_signature(self, value):
        # When the value is starting with `unknown: `, we force the value to
        # UNKNOWN to account for any unknown value sent by Firefox, see:
        # https://searchfox.org/mozilla-central/rev/b368ed8b48c0ea8ed2f1948e4776a6fbb5976dff/toolkit/mozapps/extensions/AbuseReporter.sys.mjs#218-219
        if isinstance(value, str) and value.lower().startswith('unknown: '):
            return 'unknown'
        return value

    def to_internal_value(self, data):
        # We want to accept unknown incoming data for `addon_install_method`,
        # `addon_install_source` and `addon_signature`, we have to transform it
        # here, we can't do it in a custom validation method because validation
        # would be skipped entirely if the value is not a valid choice.
        if 'addon_install_method' in data:
            data['addon_install_method'] = self.handle_unknown_install_method_or_source(
                data, 'addon_install_method'
            )
        if 'addon_install_source' in data:
            data['addon_install_source'] = self.handle_unknown_install_method_or_source(
                data, 'addon_install_source'
            )
        if 'addon_signature' in data:
            data['addon_signature'] = self.handle_addon_signature(
                data['addon_signature']
            )
        self.validate_target(data, 'addon')
        view = self.context.get('view')
        output = {'guid': view.get_guid()}
        # Pop 'addon' from data before passing that data to super(), we don't
        # need it - we're only recording the guid and it's coming from the view
        data.pop('addon')
        output.update(super().to_internal_value(data))
        return output

    def get_addon(self, obj) -> AddonDict:
        output = {
            'guid': obj.guid,
            'id': None,
            'slug': None,
        }
        if view := self.context.get('view'):
            try:
                addon = view.get_target_object()
                output['id'] = addon.pk
                output['slug'] = addon.slug
            except (Http404, UnavailableForLegalReasons):
                # We accept abuse reports against unknown guids or guids
                # belonging to non-public/disabled/deleted/georestricted
                # add-ons, but don't want to reveal the slug or id of those
                # add-ons.
                pass
        return output


class UserAbuseReportSerializer(BaseAbuseReportSerializer):
    user = BaseUserSerializer(required=False)  # We validate it ourselves.

    class Meta:
        model = AbuseReport
        fields = BaseAbuseReportSerializer.Meta.fields + ('user',)

    def to_internal_value(self, data):
        view = self.context.get('view')
        self.validate_target(data, 'user')
        output = {'user': view.get_target_object()}
        # Pop 'user' before passing it to super(), we already have the
        # output value and did the validation above.
        data.pop('user')
        output.update(super().to_internal_value(data))
        return output


class RatingAbuseReportSerializer(BaseAbuseReportSerializer):
    rating = serializers.SerializerMethodField()

    class Meta:
        model = AbuseReport
        fields = BaseAbuseReportSerializer.Meta.fields + ('rating',)

    def to_internal_value(self, data):
        self.validate_target(data, 'rating')
        view = self.context.get('view')
        output = {'rating': view.get_target_object()}
        # Pop 'rating' before passing it to super(), we already have the
        # output value and did the validation above.
        data.pop('rating')
        output.update(super().to_internal_value(data))
        return output

    def get_rating(self, obj):
        return {'id': obj.rating.pk}


class CollectionAbuseReportSerializer(BaseAbuseReportSerializer):
    class CollectionIdSerializer(CollectionSerializer):
        class Meta(CollectionSerializer.Meta):
            fields = ('id',)

    collection = CollectionIdSerializer(read_only=True)

    class Meta(BaseAbuseReportSerializer.Meta):
        fields = BaseAbuseReportSerializer.Meta.fields + ('collection',)

    def to_internal_value(self, data):
        self.validate_target(data, 'collection')
        view = self.context.get('view')
        collection = view.get_target_object()
        # Pop 'collection' before passing it to super(), we already have the
        # output value and did the validation above.
        data.pop('collection', None)
        validated_data = super().to_internal_value(data)
        validated_data['collection'] = collection
        return validated_data
