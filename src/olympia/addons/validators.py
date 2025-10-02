from django import forms
from django.conf import settings
from django.utils.translation import gettext

from rest_framework import exceptions, fields

from olympia import amo
from olympia.amo.utils import find_language
from olympia.versions.models import License

from .models import Addon
from .utils import validate_addon_name


class ValidateAddonName:
    requires_context = True

    def __call__(self, value, serializer_field):
        user = serializer_field.context['request'].user
        try:
            validate_addon_name(value, user)
        except forms.ValidationError as exc:
            raise exceptions.ValidationError(exc.message) from exc


class VersionLicenseValidator:
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
            if channel == amo.CHANNEL_LISTED and not license_:
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

        is_theme = serializer.addon_type == amo.ADDON_STATICTHEME
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
        return any(val for val in values if val) if values else bool(addon.get(field))

    def get_addon_data(self, serializer):
        if not serializer.instance:
            # if it's a new add-on, default values will come from parsed_data.
            parsed = serializer.fields['version'].parsed_data
            return {field: parsed.get(field) for field in self.fields}
        else:
            # otherwise extract the existing addon data
            return {field: getattr(serializer.instance, field) for field in self.fields}

    def get_channel(self, data):
        upload = data.get('version', {}).get('upload')
        return upload.channel if upload else None

    def __call__(self, data, serializer):
        if not serializer.partial and self.get_channel(data) == amo.CHANNEL_LISTED:
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


class VersionAddonMetadataValidator(AddonMetadataValidator):
    def get_addon_data(self, serializer):
        addon = getattr(serializer, 'addon', None)
        return {field: getattr(addon, field, None) for field in self.fields}

    def get_channel(self, data):
        return super().get_channel({'version': data})

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
            ) from exc


class AddonDefaultLocaleValidator:
    requires_context = True

    def __call__(self, data, serializer):
        from olympia.api.fields import TranslationSerializerField

        new_default = data.get('default_locale')

        if serializer.instance and not new_default:
            # We can skip updates to existing add-ons with no default_locale changes.
            return
        if not serializer.instance:
            parsed_data = serializer.fields['version'].parsed_data
            # Addon.resolve_webext_translations does find_language to check if l10n
            if lang := find_language(parsed_data.get('default_locale')):
                xpi_trans = Addon.resolve_webext_translations(
                    parsed_data,
                    data['version']['upload'],
                    use_default_locale_fallback=False,
                )
                new_default = new_default or lang
            else:
                xpi_trans = None
                new_default = new_default or settings.LANGUAGE_CODE

        fields = [
            (name, field)
            for name, field in serializer.fields.items()
            if isinstance(field, TranslationSerializerField)
        ]
        errors = {}
        # confirm all the translated fields have a value in this new locale
        for field_name, field in fields:
            if serializer.instance:
                # for an existing addon we need to consider all the existing values
                existing = field.fetch_all_translations(
                    serializer.instance, field.get_source_field(serializer.instance)
                )
                all_translations = {
                    loc: val
                    for loc, val in {**existing, **data.get(field_name, {})}.items()
                    if val is not None
                }
            elif field_name in data:
                # for a new addon a value in data overrides the xpi value/translations
                all_translations = {
                    loc: val
                    for loc, val in data.get(field_name, {}).items()
                    if val is not None
                }
            elif xpi_trans:
                # else we need to check the xpi localization - if there is xpi l10n
                all_translations = xpi_trans.get(field_name)
            else:
                all_translations = None

            if all_translations and new_default not in all_translations:
                errors[field_name] = TranslationSerializerField.default_error_messages[
                    'default_locale_required'
                ].format(lang_code=new_default)

        if errors:
            raise exceptions.ValidationError(errors)


class NoFallbackDefaultLocaleValidator:
    """This validator can be used with serializers for models that don't specify a
    fallback locale field.  (If the model does it requires more handling)"""

    requires_context = True

    def __call__(self, data, serializer):
        from olympia.api.fields import TranslationSerializerField

        if serializer.instance:
            return
        fields = [
            (name, field)
            for name, field in serializer.fields.items()
            if isinstance(field, TranslationSerializerField)
        ]
        errors = {}
        default = settings.LANGUAGE_CODE
        for field_name, field in fields:
            if field_name in data:
                locales = {
                    loc
                    for loc, val in data.get(field_name, {}).items()
                    if val is not None
                }

                if locales and default not in locales:
                    errors[field_name] = field.default_error_messages[
                        'default_locale_required'
                    ].format(lang_code=default)

        if errors:
            raise exceptions.ValidationError(errors)


class MatchingGuidValidator:
    requires_context = True

    def __call__(self, data, serializer):
        if view_guid := serializer.context['view'].kwargs.get('guid'):
            if not (manifest_guid := serializer.parsed_data.get('guid')):
                raise exceptions.ValidationError(
                    gettext('A GUID must be specified in the manifest.')
                )
            elif manifest_guid != view_guid:
                raise exceptions.ValidationError(
                    gettext('GUID mismatch between the URL and manifest.')
                )


class ReviewedSourceFileValidator:
    requires_context = True

    def __call__(self, value, serializer_field):
        if (
            (instance := serializer_field.parent.instance)
            and instance.human_review_date
            and not instance.pending_rejection
        ):
            raise exceptions.ValidationError(
                gettext(
                    'Source cannot be changed because this version has been reviewed '
                    'by Mozilla.'
                )
            )


class CanSetCompatibilityValidator:
    requires_context = True

    def __call__(self, data, serializer):
        def field_default():
            try:
                return serializer.fields['compatibility'].get_default()
            except fields.SkipField:
                return None

        if (
            not Addon.type_can_set_compatibility(serializer.addon_type)
            and 'compatible_apps' in data
            and data.get('compatible_apps') != field_default()
        ):
            raise exceptions.ValidationError(
                {
                    'compatibility': gettext(
                        'This type of add-on does not allow custom compatibility.'
                    )
                }
            )


class NoThemesValidator:
    requires_context = True

    def __call__(self, data, serializer):
        addon = (
            serializer.instance
            if isinstance(serializer.instance, Addon)
            else serializer.context['view'].get_addon_object()
        )
        if addon.type == amo.ADDON_STATICTHEME:
            raise exceptions.ValidationError(
                gettext('This endpoint is not valid for Themes.')
            )
