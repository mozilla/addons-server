import os
import tarfile
import zipfile

from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.http.request import QueryDict
from django.urls import reverse

from rest_framework import fields, exceptions, serializers

from olympia import amo
from olympia.amo.utils import ImageCheck, sorted_groupby
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import (
    ESTranslationSerializerField,
    GetTextTranslationSerializerField,
    OutgoingURLField,
    TranslationSerializerField,
)
from olympia.applications.models import AppVersion
from olympia.constants.applications import APPS
from olympia.constants.categories import CATEGORIES
from olympia.constants.licenses import LICENSES_BY_SLUG
from olympia.files.utils import SafeZip, archive_member_validator
from olympia.versions.models import (
    ApplicationsVersions,
    License,
    VALID_SOURCE_EXTENSIONS,
)


class CategoriesSerializerField(serializers.Field):
    def to_internal_value(self, data):
        try:
            categories = []
            for app_name, category_names in data.items():
                if len(category_names) > amo.MAX_CATEGORIES:
                    raise exceptions.ValidationError(
                        'Maximum number of categories per application '
                        f'({amo.MAX_CATEGORIES}) exceeded'
                    )
                if len(category_names) > 1 and 'other' in category_names:
                    raise exceptions.ValidationError(
                        'The "other" category cannot be combined with another category'
                    )
                app_cats = CATEGORIES[APPS[app_name].id]
                # We don't know the addon_type at this point, so try them all and we'll
                # drop anything that's wrong later in AddonSerializer.validate
                all_cat_slugs = set()
                for type_cats in app_cats.values():
                    categories.extend(
                        type_cats[name] for name in category_names if name in type_cats
                    )
                    all_cat_slugs.update(type_cats.keys())
                # Now double-check all the category names were found
                if not all_cat_slugs.issuperset(category_names):
                    raise exceptions.ValidationError('Invalid category name.')
            return categories
        except KeyError:
            raise exceptions.ValidationError('Invalid app name.')

    def to_representation(self, value):
        grouped = sorted_groupby(
            sorted(value),
            key=lambda x: getattr(amo.APP_IDS.get(x.application), 'short', ''),
        )
        return {
            app_name: [cat.slug for cat in categories]
            for app_name, categories in grouped
        }


class ContributionSerializerField(OutgoingURLField):
    def to_representation(self, value):
        if not value:
            # don't add anything when it's not set.
            return value
        parts = urlsplit(value)
        query = QueryDict(parts.query, mutable=True)
        query.update(amo.CONTRIBUTE_UTM_PARAMS)
        return super().to_representation(
            urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    parts.path,
                    query.urlencode(),
                    parts.fragment,
                )
            )
        )

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        parsed_url = urlsplit(data)

        if not parsed_url.hostname.endswith(amo.VALID_CONTRIBUTION_DOMAINS):
            raise exceptions.ValidationError(
                'URL domain must be one of '
                f'[{", ".join(amo.VALID_CONTRIBUTION_DOMAINS)}], or a subdomain.'
            )
        elif parsed_url.hostname == 'github.com' and not parsed_url.path.startswith(
            '/sponsors/'
        ):
            # Issue 15497, validate path for GitHub Sponsors
            raise exceptions.ValidationError(
                'URL path for GitHub Sponsors must contain /sponsors/.'
            )

        return data


class LicenseNameSerializerField(serializers.Field):
    """Field to handle license name translations.

    Builtin licenses, for better or worse, don't necessarily have their name
    translated in the database like custom licenses. Instead, the string is in
    this repos, and translated using gettext. This field deals with that
    difference, delegating the rendering to TranslationSerializerField or
    GetTextTranslationSerializerField depending on what the license instance
    is.
    """

    builtin_translation_field_class = GetTextTranslationSerializerField
    custom_translation_field_class = TranslationSerializerField

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.builtin_translation_field = self.builtin_translation_field_class()
        self.custom_translation_field = self.custom_translation_field_class()

    def bind(self, field_name, parent):
        super().bind(field_name, parent)
        self.builtin_translation_field.bind(field_name, parent)
        self.custom_translation_field.bind(field_name, parent)

    def get_attribute(self, obj):
        if obj._constant:
            return self.builtin_translation_field.get_attribute(obj._constant)
        else:
            return self.custom_translation_field.get_attribute(obj)

    def to_representation(self, obj):
        # Like TranslationSerializerField, the bulk of the logic is in
        # get_attribute(), we just have to return the data at this point.
        return obj

    def run_validation(self, data=fields.empty):
        return self.custom_translation_field.run_validation(data)

    def to_internal_value(self, value):
        return self.custom_translation_field.to_internal_value(value)


class ESLicenseNameSerializerField(LicenseNameSerializerField):
    """Like LicenseNameSerializerField, but uses the data from ES to avoid
    a database query for custom licenses.

    BaseESSerializer automatically changes
    TranslationSerializerField to ESTranslationSerializerField for all base
    fields on the serializer, but License name has its own special field to
    handle builtin licences so it's done separately."""

    custom_translation_field_class = ESTranslationSerializerField

    def attach_translations(self, obj, data, field_name):
        return self.custom_translation_field.attach_translations(obj, data, field_name)


class LicenseSlugSerializerField(serializers.SlugRelatedField):
    def __init__(self, **kwargs):
        super().__init__(
            slug_field='builtin',
            queryset=License.objects.exclude(builtin=License.OTHER),
            **kwargs,
        )

    def to_internal_value(self, data):
        license_ = LICENSES_BY_SLUG.get(data)
        if not license_:
            self.fail('invalid')
        return super().to_internal_value(license_.builtin)


class SourceFileField(serializers.FileField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        # Ensure the file type is one we support.
        if not data.name.endswith(VALID_SOURCE_EXTENSIONS):
            error_msg = (
                'Unsupported file type, please upload an archive file ({extensions}).'
            )
            raise exceptions.ValidationError(
                error_msg.format(extensions=(', '.join(VALID_SOURCE_EXTENSIONS)))
            )

        # Check inside to see if the file extension matches the content.
        try:
            _, ext = os.path.splitext(data.name)
            if ext == '.zip':
                # testzip() returns None if there are no broken CRCs.
                if SafeZip(data).zip_file.testzip() is not None:
                    raise zipfile.BadZipFile()
            else:
                # For tar files we need to do a little more work.
                mode = 'r:bz2' if ext == '.bz2' else 'r:gz'
                with tarfile.open(mode=mode, fileobj=data) as archive:
                    for member in archive.getmembers():
                        archive_member_validator(archive, member)
        except (zipfile.BadZipFile, tarfile.ReadError, OSError, EOFError):
            raise exceptions.ValidationError('Invalid or broken archive.')

        return data

    def to_representation(self, value):
        if not value:
            return None
        else:
            return absolutify(reverse('downloads.source', args=(self.parent.id,)))


class VersionCompatabilityField(serializers.Field):
    def to_internal_value(self, data):
        """Note: this returns unsaved and incomplete ApplicationsVersions objects that
        need to have version set, and may have missing min or max AppVersion instances
        for new Version instances. (As intended - we want to be able to partially
        specify min or max and have the manifest or defaults be instead used).
        """
        try:
            if isinstance(data, list):
                # if it's a list of apps, normalize into a dict first
                data = {key: {} for key in data}
            if isinstance(data, dict):
                version = self.parent.instance
                existing = version.compatible_apps if version else {}
                qs = AppVersion.objects
                internal = {}
                for app_name, min_max in data.items():
                    app = amo.APPS[app_name]
                    apps_versions = existing.get(
                        app, ApplicationsVersions(application=app.id)
                    )

                    app_qs = qs.filter(application=app.id)
                    if 'max' in min_max:
                        apps_versions.max = app_qs.get(version=min_max['max'])
                    elif version:
                        apps_versions.max = app_qs.get(
                            version=amo.DEFAULT_WEBEXT_MAX_VERSION
                        )

                    app_qs = app_qs.exclude(version='*')
                    if 'min' in min_max:
                        apps_versions.min = app_qs.get(version=min_max['min'])
                    elif version:
                        apps_versions.min = app_qs.get(
                            version=amo.DEFAULT_WEBEXT_MIN_VERSIONS[app]
                        )

                    internal[app] = apps_versions
                return internal
            else:
                # if it's neither it's not a valid input
                raise exceptions.ValidationError('Invalid value')
        except KeyError:
            raise exceptions.ValidationError('Invalid app specified')
        except AppVersion.DoesNotExist:
            raise exceptions.ValidationError('Unknown app version specified')

    def to_representation(self, value):
        return {
            app.short: (
                {
                    'min': compat.min.version,
                    'max': compat.max.version,
                }
                if compat
                else {
                    'min': amo.D2C_MIN_VERSIONS.get(app.id, '1.0'),
                    'max': amo.FAKE_MAX_VERSION,
                }
            )
            for app, compat in value.items()
        }


class IconField(serializers.ImageField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        image_check = ImageCheck(data)

        if data.content_type not in amo.IMG_TYPES or not image_check.is_image():
            raise serializers.ValidationError('Icons must be either PNG or JPG.')
        errors = []

        if image_check.is_animated():
            errors.append('Icons cannot be animated.')

        if data.size > settings.MAX_ICON_UPLOAD_SIZE:
            errors.append(
                'Please use images smaller than %dMB'
                % (settings.MAX_ICON_UPLOAD_SIZE / 1024 / 1024)
            )

        icon_size = image_check.size
        if icon_size[0] != icon_size[1]:
            errors.append('Icon must be square (same width and height).')

        if errors:
            raise serializers.ValidationError(errors)

        return data
