import functools

from django import forms
from django.utils.translation import gettext

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.addons.utils import (
    validate_version_number_is_gt_latest_signed_listed_version,
    webext_version_stats,
)
from olympia.amo.decorators import use_primary_db
from olympia.api.authentication import JWTKeyAuthentication
from olympia.api.throttling import addon_submission_throttles
from olympia.devhub.permissions import IsSubmissionAllowedFor
from olympia.devhub.views import handle_upload as devhub_handle_upload
from olympia.files.models import FileUpload
from olympia.files.utils import parse_addon
from olympia.versions import views as version_views
from olympia.versions.models import Version

from .serializers import SigningFileUploadSerializer


log = olympia.core.logger.getLogger('signing')


def with_addon(allow_missing=False):
    """Call the view function with an addon instead of a guid. This will try
    find an addon with the guid and verify the user's permissions. If the
    add-on is not found it will 404 when allow_missing is False otherwise it
    will call the view with addon set to None."""

    def wrapper(fn):
        @functools.wraps(fn)
        def inner(view, request, **kwargs):
            guid = kwargs.get('guid', None)
            try:
                if guid is None:
                    raise Addon.DoesNotExist('No Add-on ID')
                addon = Addon.objects.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    msg = gettext('Could not find Add-on with ID "{}".').format(guid)
                    return Response({'error': msg}, status=status.HTTP_404_NOT_FOUND)
            # Call the view if there is no add-on, the current user is an
            # author of the add-on or the current user is an admin and the
            # request is a GET.
            has_perm = addon is None or (
                addon.has_author(request.user)
                or (
                    request.method == 'GET'
                    and acl.action_allowed_for(
                        request.user, amo.permissions.ADDONS_EDIT
                    )
                )
            )

            if has_perm:
                return fn(view, request, addon=addon, **kwargs)
            else:
                return Response(
                    {'error': gettext('You do not own this add-on.')},
                    status=status.HTTP_403_FORBIDDEN,
                )

        return inner

    return wrapper


class VersionView(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated, IsSubmissionAllowedFor]
    throttle_classes = addon_submission_throttles

    def post(self, request, *args, **kwargs):
        version_string = request.data.get('version', None)

        try:
            file_upload, _ = self.handle_upload(request, None, version_string)
        except forms.ValidationError as exc:
            return Response(
                {'error': exc.message}, status=exc.code or status.HTTP_400_BAD_REQUEST
            )

        serializer = SigningFileUploadSerializer(
            file_upload, context={'request': request}
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @with_addon(allow_missing=True)
    def put(self, request, addon, version_string, guid=None):
        try:
            file_upload, created = self.handle_upload(
                request, addon, version_string, guid=guid
            )
        except forms.ValidationError as exc:
            return Response(
                {'error': exc.message}, status=exc.code or status.HTTP_400_BAD_REQUEST
            )

        status_code = status.HTTP_201_CREATED if created else status.HTTP_202_ACCEPTED

        serializer = SigningFileUploadSerializer(
            file_upload, context={'request': request}
        )
        return Response(serializer.data, status=status_code)

    @use_primary_db
    def handle_upload(self, request, addon, version_string, guid=None):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            raise forms.ValidationError(
                gettext('Missing "upload" key in multipart file data.'),
                status.HTTP_400_BAD_REQUEST,
            )

        # Parse the file to get and validate package data with the addon.
        parsed_data = parse_addon(filedata, addon, user=request.user)

        if addon is not None and addon.status == amo.STATUS_DISABLED:
            msg = gettext(
                'You cannot add versions to an add-on that has status: %s.'
                % amo.STATUS_CHOICES_ADDON[amo.STATUS_DISABLED]
            )
            raise forms.ValidationError(msg, status.HTTP_400_BAD_REQUEST)

        version_string = version_string or parsed_data['version']

        if version_string and parsed_data['version'] != version_string:
            raise forms.ValidationError(
                gettext('Version does not match the manifest file.'),
                status.HTTP_400_BAD_REQUEST,
            )

        existing_version = (
            addon
            and Version.unfiltered.filter(addon=addon, version=version_string).last()
        )
        if existing_version:
            if existing_version.deleted:
                msg = gettext('Version {version} was uploaded before and deleted.')
            else:
                msg = gettext('Version {version} already exists.')
            raise forms.ValidationError(
                msg.format(version=version_string), status.HTTP_409_CONFLICT
            )

        package_guid = parsed_data.get('guid', None)

        if guid is not None and not addon and not package_guid:
            # No guid was present in the package, but one was provided in the
            # URL, so we take it instead of generating one ourselves. There is
            # an extra validation check for those: guids passed in the URL are
            # not allowed to be longer than 64 chars.
            if len(guid) > 64:
                raise forms.ValidationError(
                    gettext(
                        "Please specify your Add-on ID in the manifest if it's "
                        'longer than 64 characters.'
                    )
                )

            parsed_data['guid'] = guid
        elif not guid and package_guid:
            guid = package_guid

        if guid:
            # If we did get a guid, regardless of its source, validate it now
            # before creating anything.
            if not amo.ADDON_GUID_PATTERN.match(guid):
                raise forms.ValidationError(
                    gettext('Invalid Add-on ID in URL or package'),
                    status.HTTP_400_BAD_REQUEST,
                )

        # channel will be ignored for new addons.
        if addon is None:
            channel = amo.CHANNEL_UNLISTED  # New is always unlisted.
            addon = Addon.initialize_addon_from_upload(
                data=parsed_data, upload=filedata, channel=channel, user=request.user
            )
            created = True
        else:
            created = False
            channel_param = request.POST.get('channel')
            channel = amo.CHANNEL_CHOICES_LOOKUP.get(channel_param)
            if not channel:
                last_version = addon.find_latest_version(None, exclude=())
                if last_version:
                    channel = last_version.channel
                else:
                    channel = amo.CHANNEL_UNLISTED  # Treat as new.

            if addon.disabled_by_user and channel == amo.CHANNEL_LISTED:
                msg = gettext(
                    'You cannot add listed versions to an add-on set to '
                    '"Invisible" state.'
                )
                raise forms.ValidationError(msg, status.HTTP_400_BAD_REQUEST)

            will_have_listed = channel == amo.CHANNEL_LISTED
            if not addon.has_complete_metadata(has_listed_versions=will_have_listed):
                raise forms.ValidationError(
                    gettext(
                        'You cannot add a listed version to this add-on '
                        'via the API due to missing metadata. '
                        'Please submit via the website'
                    ),
                    status.HTTP_400_BAD_REQUEST,
                )
        if channel == amo.CHANNEL_LISTED and (
            error_message := validate_version_number_is_gt_latest_signed_listed_version(
                addon, version_string
            )
        ):
            raise forms.ValidationError(
                error_message,
                status.HTTP_409_CONFLICT,
            )

        # Note: The following function call contains a log statement that is
        # used by foxsec-pipeline - if refactoring, keep in mind we need to
        # trigger the same log statement.
        file_upload = devhub_handle_upload(
            filedata=filedata,
            request=request,
            addon=addon,
            submit=True,
            channel=channel,
            source=amo.UPLOAD_SOURCE_SIGNING_API,
        )

        webext_version_stats(request, 'signing.submission')

        return file_upload, created

    @use_primary_db
    @with_addon()
    def get(self, request, addon, version_string, uuid=None, guid=None):
        file_upload_qs = FileUpload.objects.filter(addon=addon, version=version_string)

        try:
            if uuid is None:
                file_upload = file_upload_qs.latest()
                log.info(
                    'getting latest upload for {addon} {version}: '
                    '{file_upload.uuid}'.format(
                        addon=addon, version=version_string, file_upload=file_upload
                    )
                )
            else:
                file_upload = file_upload_qs.get(uuid=uuid)
                log.info(
                    'getting specific upload for {addon} {version} '
                    '{uuid}: {file_upload.uuid}'.format(
                        addon=addon,
                        version=version_string,
                        uuid=uuid,
                        file_upload=file_upload,
                    )
                )
        except FileUpload.DoesNotExist:
            msg = gettext('No uploaded file for that add-on and version.')
            return Response({'error': msg}, status=status.HTTP_404_NOT_FOUND)

        try:
            version = addon.versions.filter(version=version_string).latest()
        except Version.DoesNotExist:
            version = None

        serializer = SigningFileUploadSerializer(
            file_upload, version=version, context={'request': request}
        )
        return Response(serializer.data)


class SignedFile(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @use_primary_db
    def get(self, request, file_id, filename=None):
        return version_views.download_file(request, file_id, filename=filename)
