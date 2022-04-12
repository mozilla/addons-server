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
                {'license': gettext('Wrong addon type for this license.')},
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
