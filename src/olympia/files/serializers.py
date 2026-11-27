from django import forms
from django.utils.translation import gettext

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import ReverseChoiceField
from olympia.api.serializers import AMOModelSerializer
from olympia.versions.utils import (
    validate_listed_version_allowed,
    validate_version_number_does_not_exist,
    validate_version_number_is_gt_latest_signed_listed_version,
)

from .models import FileUpload
from .utils import DuplicateAddonID, parse_addon


class FileUploadSerializer(AMOModelSerializer):
    uuid = serializers.UUIDField(format='hex')
    channel = ReverseChoiceField(choices=list(amo.CHANNEL_CHOICES_API.items()))
    processed = serializers.BooleanField()
    valid = serializers.BooleanField(source='passed_all_validations')
    validation = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    manifest_data = serializers.SerializerMethodField()

    class Meta:
        model = FileUpload
        fields = [
            'uuid',
            'channel',
            'manifest_data',
            'processed',
            'submitted',
            'url',
            'valid',
            'validation',
            'version',
        ]

    submission_check = None

    def to_representation(self, instance):
        self.submission_check = self.check_submission(instance)
        data = super().to_representation(instance)
        if self.submission_check and self.submission_check['messages']:
            messages = self.submission_check['messages']
            validation = data['validation'] or {'errors': 0, 'messages': []}
            validation['messages'][:0] = messages
            validation['errors'] = validation.get('errors', 0) + len(messages)
            data['validation'] = validation
            data['valid'] = False
        return data

    def check_submission(self, instance):
        """Opt-in early run of the checks that otherwise only fail on submission."""
        if (
            not self.context.get('full_check')
            or not instance.passed_all_validations
            or instance.submitted
        ):
            return None
        addon = self.context.get('addon')
        user = self.context['request'].user
        try:
            parsed = parse_addon(instance, addon=addon, user=user)
        except DuplicateAddonID as exc:
            return {
                'parsed': None,
                'messages': [self.duplicate_addon_id_message(exc, user)],
            }
        except forms.ValidationError as exc:
            return {
                'parsed': None,
                'messages': [
                    self.error_message('invalid', msg) for msg in exc.messages
                ],
            }
        messages = []
        if addon:
            version_string = parsed.get('version')
            listed = instance.channel == amo.CHANNEL_LISTED
            if error := validate_version_number_does_not_exist(addon, version_string):
                messages.append(self.error_message('version_exists', error))
            elif listed and (
                error := validate_version_number_is_gt_latest_signed_listed_version(
                    addon, version_string
                )
            ):
                messages.append(self.error_message('version_not_greater', error))
            if listed and (error := validate_listed_version_allowed(addon)):
                messages.append(self.error_message('listed_not_allowed', error))
        return {'parsed': parsed, 'messages': messages}

    def error_message(self, code, message):
        return {
            'id': ['submission', code],
            'type': 'error',
            'message': message,
            'tier': 1,
        }

    def duplicate_addon_id_message(self, exc, user):
        message = self.error_message('duplicate_addon_id', exc.messages[0])
        # Only the add-on's own authors get pointed at it: anyone else would
        # learn which add-on (if any) owns the ID.
        existing = (
            Addon.objects.filter(guid=exc.guid)
            .exclude(status=amo.STATUS_DISABLED)
            .first()
        )
        if existing and existing.has_author(user):
            message['message'] = gettext(
                'This add-on ID is already used by your add-on.'
            )
            message['addon'] = {
                'id': existing.id,
                'slug': existing.slug,
                'name': str(existing.name),
            }
        return message

    def get_validation(self, instance):
        return instance.load_validation() if instance.validation else None

    def get_url(self, instance):
        return absolutify(
            drf_reverse(
                'addon-upload-detail',
                request=self.context.get('request'),
                args=[instance.uuid.hex],
            )
        )

    def get_manifest_data(self, instance):
        if (
            getattr(self.context.get('view'), 'action', None) == 'list'
            or not instance.passed_all_validations
            or instance.submitted
        ):
            return None
        if check := self.submission_check:
            if check['messages']:
                return None
            parsed = check['parsed']
        else:
            try:
                parsed = parse_addon(instance, minimal=True)
            except forms.ValidationError:
                return None
        parsed = Addon.resolve_webext_translations(parsed, instance)
        return {
            **{field: parsed.get(field) for field in ('name', 'summary', 'homepage')},
            'type': amo.ADDON_TYPE_CHOICES_API.get(parsed.get('type')),
            'explicitly_compatible_with_android': parsed.get(
                'explicitly_compatible_with_android', False
            ),
        }
