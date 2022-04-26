from django import forms
from django.utils.translation import gettext

from rest_framework import exceptions

from olympia import amo
from olympia.versions.models import License

from .utils import verify_mozilla_trademark


class VerifyMozillaTrademark:
    requires_context = True

    def __call__(self, value, serializer_field):
        user = serializer_field.context['request'].user
        try:
            verify_mozilla_trademark(value, user)
        except forms.ValidationError as exc:
            raise exceptions.ValidationError(exc.message)


class ValidateVersionLicense:
    requires_context = True

    def __call__(self, data, serializer):
        from olympia.addons.serializers import LicenseSerializer

        # We have to check the raw request data because data from both fields will be
        # under `license` at this point.
        if (
            (request := serializer.context.get('request'))
            and 'license' in request.data
            and 'custom_license' in request.data
        ):
            raise exceptions.ValidationError(
                gettext(
                    'Both `license` and `custom_license` cannot be provided together.'
                )
            )

        license_ = data.get('license')
        is_custom = isinstance(license_, dict)
        if not serializer.instance:
            channel = data['upload'].channel
            if channel == amo.RELEASE_CHANNEL_LISTED and not license_:
                # If the previous version has a license we can use that, otherwise its
                # required. This is what we do in Version.from_upload to get the
                # license.
                previous_version = (
                    serializer.addon
                    and serializer.addon.find_latest_version(
                        channel=channel, exclude=()
                    )
                )
                if not previous_version or not previous_version.license_id:
                    raise exceptions.ValidationError(
                        {
                            'license': (
                                gettext(
                                    'This field, or custom_license, is required for '
                                    'listed versions.'
                                )
                            )
                        },
                        code='required',
                    )
            addon_type = serializer.parsed_data['type']
        else:
            # In the case where:
            # - we are updating the version;
            # - the existing license is built-in;
            # - and we setting a custom license:
            # we need to force the validation as if was a new license because we create
            # a new instance for it in DeveloperVersionSerializer.update.
            if (
                is_custom
                and (existing := serializer.instance.license)
                and existing.builtin != License.OTHER
                and not (custom_license := LicenseSerializer(data=license_)).is_valid()
            ):
                raise exceptions.ValidationError(
                    {'custom_license': custom_license.errors}
                )
            addon_type = serializer.addon.type

        is_theme = addon_type == amo.ADDON_STATICTHEME
        if isinstance(license_, License) and license_.creative_commons != is_theme:
            raise exceptions.ValidationError(
                {'license': gettext('Wrong add-on type for this license.')},
                code='required',
            )
        if is_custom and is_theme:
            raise exceptions.ValidationError(
                {
                    'custom_license': gettext(
                        'Custom licenses are not supported for themes.'
                    )
                },
            )


class AddonMetadataValidator:
    requires_context = True
    fields = {'name': 'name', 'summary': 'summary', 'all_categories': 'categories'}

    def has_metadata(self, data, addon, field):
        data_value = data.get(field)
        values = data_value.values() if isinstance(data_value, dict) else data_value
        return (values and any(val for val in values if val)) or bool(addon.get(field))

    def get_addon_data(self, serializer):
        if hasattr(serializer.fields.get('version'), 'parsed_data'):
            # if we have a version field it's a new addon, so get the parsed_data
            parsed = serializer.fields['version'].parsed_data
            return {field: parsed.get(field) for field in self.fields}
        else:
            # else it's a new version, so extract the existing addon data
            addon = getattr(serializer, 'addon', None)
            return {field: getattr(addon, field, None) for field in self.fields}

    def get_channel(self, data):
        upload = data.get('upload', data.get('version', {}).get('upload'))
        return upload.channel if upload else None

    def __call__(self, data, serializer):
        if (
            not serializer.instance
            and self.get_channel(data) == amo.RELEASE_CHANNEL_LISTED
        ):
            # Check that the required metadata is set for an addon with listed versions
            addon_data = self.get_addon_data(serializer)
            # This is replicating what Addon.get_required_metadata does
            required_msg = gettext(
                'This field is required for add-ons with listed versions.'
            )
            missing_metadata = {
                serializer_field: required_msg
                for data_field, serializer_field in self.fields.items()
                if not self.has_metadata(data, addon_data, data_field)
            }
            if missing_metadata:
                raise exceptions.ValidationError(missing_metadata, code='required')


class AddonMetadataNewVersionValidator(AddonMetadataValidator):
    def __call__(self, data, serializer):
        try:
            return super().__call__(data=data, serializer=serializer)
        except exceptions.ValidationError as exc:
            # Reformat the validation error(s) into a single error
            raise exceptions.ValidationError(
                gettext(
                    'Add-on metadata is required to be set to create a listed '
                    'version: {missing_addon_metadata}.'
                ).format(missing_addon_metadata=list(exc.detail)),
                code='required',
            )
