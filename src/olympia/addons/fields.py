import copy
import os
import tarfile
import zipfile
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.db.models import Q
from django.http.request import QueryDict
from django.urls import reverse
from django.utils.encoding import smart_str
from django.utils.translation import gettext, gettext_lazy as _

from rest_framework import exceptions, serializers

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import ImageCheck, sorted_groupby
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
from olympia.files.utils import SafeTar, SafeZip
from olympia.versions.models import (
    VALID_SOURCE_EXTENSIONS,
    ApplicationsVersions,
    License,
    Version,
)


class CategoriesSerializerField(serializers.Field):
    def to_internal_value(self, data):
        try:
            categories = []
            for app_name, category_names in data.items():
                if len(category_names) > amo.MAX_CATEGORIES:
                    raise exceptions.ValidationError(
                        gettext(
                            'Maximum number of categories per application '
                            '({MAX_CATEGORIES}) exceeded'
                        ).format(MAX_CATEGORIES=amo.MAX_CATEGORIES)
                    )
                if len(category_names) > 1 and 'other' in category_names:
                    raise exceptions.ValidationError(
                        gettext(
                            'The "other" category cannot be combined with another '
                            'category'
                        )
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
                    raise exceptions.ValidationError(gettext('Invalid category name.'))
            if not categories and self.required:
                self.fail('required')
            return categories
        except KeyError:
            raise exceptions.ValidationError(gettext('Invalid app name.'))

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
        errors = []

        if parsed_url.hostname not in amo.VALID_CONTRIBUTION_DOMAINS:
            errors.append(
                gettext('URL domain must be one of [{domains}].').format(
                    domains=', '.join(amo.VALID_CONTRIBUTION_DOMAINS)
                )
            )
        elif parsed_url.hostname == 'github.com' and not parsed_url.path.startswith(
            '/sponsors/'
        ):
            # Issue 15497, validate path for GitHub Sponsors
            errors.append(
                gettext('URL path for GitHub Sponsors must contain /sponsors/.')
            )
        if parsed_url.scheme != 'https':
            errors.append(gettext('URLs must start with https://.'))

        if errors:
            raise exceptions.ValidationError(errors)

        return data


class LicenseNameSerializerMixin:
    """Field to handle license name translations.

    Builtin licenses, for better or worse, don't necessarily have their name
    translated in the database like custom licenses. Instead, the string is in
    this repos, and translated using gettext. This field deals with that
    difference, delegating the rendering to TranslationSerializerField or
    GetTextTranslationSerializerField depending on what the license instance
    is.
    """

    builtin_translation_field_class = GetTextTranslationSerializerField

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.builtin_translation_field = self.builtin_translation_field_class(
            *args, **kwargs
        )

    def bind(self, field_name, parent):
        super().bind(field_name, parent)
        self.builtin_translation_field.bind(field_name, parent)

    def get_attribute(self, obj):
        if obj._constant:
            return self.builtin_translation_field.get_attribute(obj._constant)
        else:
            return super().get_attribute(obj)

    def to_representation(self, obj):
        # Like TranslationSerializerField, the bulk of the logic is in
        # get_attribute(), we just have to return the data at this point.
        return obj


class LicenseNameSerializerField(
    LicenseNameSerializerMixin, TranslationSerializerField
):
    def get_es_instance(self):
        return ESLicenseNameSerializerField(source=self.source)


class ESLicenseNameSerializerField(
    LicenseNameSerializerMixin, ESTranslationSerializerField
):
    """Like LicenseNameSerializerField, but uses the data from ES to avoid
    a database query for custom licenses."""


class LicenseSlugSerializerField(serializers.RelatedField):
    default_error_messages = {
        'does_not_exist': _('License with slug={value} does not exist.'),
    }

    def __init__(self, **kwargs):
        super().__init__(
            queryset=License.objects.exclude(builtin=License.OTHER), **kwargs
        )

    def to_internal_value(self, data):
        try:
            license_ = LICENSES_BY_SLUG[data]
            return self.get_queryset().get(builtin=license_.builtin)
        except (License.DoesNotExist, KeyError, TypeError):
            self.fail('does_not_exist', value=smart_str(data))


class SourceFileField(serializers.FileField):
    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        # Ensure the file type is one we support.
        if not data.name.endswith(VALID_SOURCE_EXTENSIONS):
            error_msg = gettext(
                'Unsupported file type, please upload an archive file ({extensions}).'
            )
            raise exceptions.ValidationError(
                error_msg.format(extensions=(', '.join(VALID_SOURCE_EXTENSIONS)))
            )

        # Check inside to see if the file extension matches the content.
        try:
            _, ext = os.path.splitext(data.name)
            if ext == '.zip':
                # For zip files, opening them though SafeZip() checks that we
                # can accept the file and testzip() on top of that returns None
                # if there are no broken CRCs.
                if SafeZip(data).zip_file.testzip() is not None:
                    raise zipfile.BadZipFile()
            else:
                # For tar files, opening them through SafeTar.open() checks
                # that we can accept it.
                mode = 'r:bz2' if ext == '.bz2' else 'r:gz'
                with SafeTar.open(mode=mode, fileobj=data):
                    pass
        except (zipfile.BadZipFile, tarfile.ReadError, OSError, EOFError):
            raise exceptions.ValidationError(gettext('Invalid or broken archive.'))

        return data

    def to_representation(self, value):
        if not value:
            return None
        else:
            return absolutify(reverse('downloads.source', args=(self.parent.id,)))


class VersionCompatibilityField(serializers.Field):
    def to_internal_value(self, data):
        """Note: this returns unsaved and incomplete ApplicationsVersions objects that
        need to have version set, and may have missing min or max AppVersion instances
        for new Version instances. (As intended - we want to be able to partially
        specify min or max and have the manifest or defaults be instead used).
        """
        if isinstance(data, list):
            # if it's a list of apps, normalize into a dict first
            data = {key: {} for key in data}
        if not isinstance(data, dict) or data == {}:
            # if it's neither it's not a valid input
            raise exceptions.ValidationError(gettext('Invalid value'))

        version = self.parent.instance
        addon = self.parent.addon
        existing = version.compatible_apps if version else {}
        internal = {}
        for app_name, min_max in data.items():
            try:
                app = amo.APPS[app_name]
            except KeyError:
                raise exceptions.ValidationError(gettext('Invalid app specified'))

            existing_app = existing.get(app)
            # we need to copy() to avoid changing the instance before save
            apps_versions = copy.copy(existing_app) or ApplicationsVersions(
                application=app.id, version=version or Version(addon=addon)
            )
            app_version_qs = AppVersion.objects.filter(application=app.id)
            try:
                if 'max' in min_max:
                    apps_versions.max = app_version_qs.get(version=min_max['max'])
                elif version:
                    apps_versions.max = apps_versions.get_default_maximum_appversion()

            except AppVersion.DoesNotExist:
                raise exceptions.ValidationError(
                    gettext('Unknown max app version specified')
                )

            try:
                app_version_qs = app_version_qs.filter(~Q(version__contains='*'))
                if 'min' in min_max:
                    apps_versions.min = app_version_qs.get(version=min_max['min'])
                elif version:
                    apps_versions.min = apps_versions.get_default_minimum_appversion()
            except AppVersion.DoesNotExist:
                raise exceptions.ValidationError(
                    gettext('Unknown min app version specified')
                )

            # We want to validate whether or not the android range contains
            # forbidden versions. At this point the ApplicationsVersions
            # instance might be partial and completed by Version.from_upload()
            # which looks at the manifest. We can't do that here, so if either
            # the min or max provided would lead to a problematic range on its
            # own, we force the developer to explicitly set both, even though
            # what's in the manifest could resulted in a valid range.
            if (
                ('min' in min_max or 'max' in min_max)
                and apps_versions.application == amo.ANDROID.id
                and apps_versions.version_range_contains_forbidden_compatibility()
            ):
                valid_range = ApplicationsVersions.ANDROID_LIMITED_COMPATIBILITY_RANGE
                raise exceptions.ValidationError(
                    gettext(
                        'Invalid version range. For Firefox for Android, you may only '
                        'pick a range that starts with version %(max)s or higher, '
                        'or ends with lower than version %(min)s.'
                    )
                    % {'min': valid_range[0], 'max': valid_range[1]}
                )
            if existing_app and existing_app.locked_from_manifest:
                if (
                    existing_app.min != apps_versions.min
                    or existing_app.max != apps_versions.max
                ):
                    raise exceptions.ValidationError(
                        gettext(
                            'Can not override compatibility information set in the '
                            'manifest for this application (%s)'
                        )
                        % app.pretty
                    )
            else:
                apps_versions.originated_from = (
                    amo.APPVERSIONS_ORIGINATED_FROM_DEVELOPER
                )

            internal[app] = apps_versions

        # Also make sure no ApplicationsVersions that existed already and were
        # locked because manifest is the source of truth are gone.
        for app, apps_versions in existing.items():
            if apps_versions.locked_from_manifest and app not in internal:
                raise exceptions.ValidationError(
                    gettext(
                        'Can not override compatibility information set in the '
                        'manifest for this application (%s)'
                    )
                    % app.pretty
                )

        return internal

    def to_representation(self, value):
        return {
            app.short: (
                {
                    'min': compat.min.version,
                    'max': compat.max.version,
                }
                if compat
                else {
                    'min': amo.DEFAULT_WEBEXT_MIN_VERSIONS.get(
                        app, amo.DEFAULT_WEBEXT_MIN_VERSION
                    ),
                    'max': amo.FAKE_MAX_VERSION,
                }
            )
            for app, compat in value.items()
        }


class ImageField(serializers.ImageField):
    def __init__(self, *args, **kwargs):
        max_size_setting = kwargs.pop('max_size_setting', 'MAX_IMAGE_UPLOAD_SIZE')
        self.max_size = kwargs.pop('max_size', getattr(settings, max_size_setting))
        self.require_square = kwargs.pop('require_square', False)
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)

        image_check = ImageCheck(data)

        if data.content_type not in amo.IMG_TYPES or not image_check.is_image():
            raise exceptions.ValidationError(
                gettext('Images must be either PNG or JPG.')
            )
        errors = []

        if image_check.is_animated():
            errors.append(gettext('Images cannot be animated.'))

        if data.size > self.max_size:
            errors.append(
                gettext('Images must be smaller than %dMB')
                % (self.max_size / 1024 / 1024)
            )

        icon_size = image_check.size
        if self.require_square and icon_size[0] != icon_size[1]:
            errors.append('Images must be square (same width and height).')

        if errors:
            raise exceptions.ValidationError(errors)

        return data
