import functools

from django import forms
from django.conf import settings
from django.utils.translation import ugettext

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo.decorators import write
from olympia.api.authentication import JWTKeyAuthentication
from olympia.devhub.views import handle_upload
from olympia.files.models import FileUpload
from olympia.files.utils import parse_addon
from olympia.signing.serializers import FileUploadSerializer
from olympia.versions import views as version_views
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('signing')


def handle_read_only_mode(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        if settings.READ_ONLY:
            return Response(
                {'error': ugettext(
                    'Some features are temporarily disabled while we '
                    'perform website maintenance. We\'ll be back to '
                    'full capacity shortly.')},
                status=503)
        else:
            return fn(*args, **kwargs)
    return inner


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
                    raise Addon.DoesNotExist('No GUID')
                addon = Addon.unfiltered.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    msg = ugettext(
                        'Could not find add-on with id "{}".').format(guid)
                    return Response(
                        {'error': msg},
                        status=status.HTTP_404_NOT_FOUND)
            # Call the view if there is no add-on, the current user is an
            # author of the add-on or the current user is an admin and the
            # request is a GET.
            has_perm = (
                addon is None or
                (addon.has_author(request.user) or
                    (request.method == 'GET' and
                        acl.action_allowed_user(
                            request.user, amo.permissions.ADDONS_EDIT))))

            if has_perm:
                return fn(view, request, addon=addon, **kwargs)
            else:
                return Response(
                    {'error': ugettext('You do not own this addon.')},
                    status=status.HTTP_403_FORBIDDEN)
        return inner
    return wrapper


class VersionView(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @handle_read_only_mode
    def post(self, request, *args, **kwargs):
        version_string = request.data.get('version', None)

        try:
            file_upload, _ = self.handle_upload(request, None, version_string)
        except forms.ValidationError as exc:
            return Response(
                {'error': exc.message},
                status=exc.code or status.HTTP_400_BAD_REQUEST)

        return Response(FileUploadSerializer(file_upload).data,
                        status=status.HTTP_201_CREATED)

    @handle_read_only_mode
    @with_addon(allow_missing=True)
    def put(self, request, addon, version_string, guid=None):
        try:
            file_upload, created = self.handle_upload(
                request, addon, version_string, guid=guid)
        except forms.ValidationError as exc:
            return Response(
                {'error': exc.message},
                status=exc.code or status.HTTP_400_BAD_REQUEST)

        status_code = (
            status.HTTP_201_CREATED if created else status.HTTP_202_ACCEPTED)

        return Response(FileUploadSerializer(file_upload).data,
                        status=status_code)

    @write
    def handle_upload(self, request, addon, version_string, guid=None):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            raise forms.ValidationError(
                ugettext(u'Missing "upload" key in multipart file data.'),
                status.HTTP_400_BAD_REQUEST)

        # # Parse the file to get and validate package data with the addon.
        pkg = parse_addon(filedata, addon, user=request.user)

        if addon is not None and addon.status == amo.STATUS_DISABLED:
            msg = ugettext(
                'You cannot add versions to an addon that has status: %s.'
                % amo.STATUS_CHOICES_ADDON[amo.STATUS_DISABLED])
            raise forms.ValidationError(msg, status.HTTP_400_BAD_REQUEST)

        version_string = version_string or pkg['version']

        if version_string and pkg['version'] != version_string:
            raise forms.ValidationError(
                ugettext('Version does not match the manifest file.'),
                status.HTTP_400_BAD_REQUEST)

        if (addon is not None and
                addon.versions.filter(version=version_string).exists()):
            raise forms.ValidationError(
                ugettext('Version already exists.'),
                status.HTTP_409_CONFLICT)

        package_guid = pkg.get('guid', None)

        dont_allow_no_guid = (
            not addon and not package_guid and
            not pkg.get('is_webextension', False))

        if dont_allow_no_guid:
            raise forms.ValidationError(
                ugettext('Only WebExtensions are allowed to omit the GUID'),
                status.HTTP_400_BAD_REQUEST)

        if guid is not None and not addon and not package_guid:
            # No guid was present in the package, but one was provided in the
            # URL, so we take it instead of generating one ourselves. But
            # first, validate it properly.
            if len(guid) > 64:
                raise forms.ValidationError(ugettext(
                    'Please specify your Add-on GUID in the manifest if it\'s '
                    'longer than 64 characters.'
                ))

            if not amo.ADDON_GUID_PATTERN.match(guid):
                raise forms.ValidationError(
                    ugettext('Invalid GUID in URL'),
                    status.HTTP_400_BAD_REQUEST)
            pkg['guid'] = guid

        # channel will be ignored for new addons.
        if addon is None:
            channel = amo.RELEASE_CHANNEL_UNLISTED  # New is always unlisted.
            addon = Addon.initialize_addon_from_upload(
                data=pkg, upload=filedata, channel=channel, user=request.user)
            created = True
        else:
            created = False
            channel_param = request.POST.get('channel')
            channel = amo.CHANNEL_CHOICES_LOOKUP.get(channel_param)
            if not channel:
                last_version = (
                    addon.find_latest_version(None, exclude=()))
                if last_version:
                    channel = last_version.channel
                else:
                    channel = amo.RELEASE_CHANNEL_UNLISTED  # Treat as new.

            will_have_listed = channel == amo.RELEASE_CHANNEL_LISTED
            if not addon.has_complete_metadata(
                    has_listed_versions=will_have_listed):
                raise forms.ValidationError(
                    ugettext('You cannot add a listed version to this addon '
                             'via the API due to missing metadata. '
                             'Please submit via the website'),
                    status.HTTP_400_BAD_REQUEST)

        file_upload = handle_upload(
            filedata=filedata, request=request, addon=addon, submit=True,
            channel=channel)

        return file_upload, created

    @write
    @with_addon()
    def get(self, request, addon, version_string, uuid=None, guid=None):
        file_upload_qs = FileUpload.objects.filter(
            addon=addon, version=version_string)
        try:
            if uuid is None:
                file_upload = file_upload_qs.latest()
                log.info('getting latest upload for {addon} {version}: '
                         '{file_upload.uuid}'.format(
                             addon=addon, version=version_string,
                             file_upload=file_upload))
            else:
                file_upload = file_upload_qs.get(uuid=uuid)
                log.info('getting specific upload for {addon} {version} '
                         '{uuid}: {file_upload.uuid}'.format(
                             addon=addon, version=version_string, uuid=uuid,
                             file_upload=file_upload))
        except FileUpload.DoesNotExist:
            msg = ugettext('No uploaded file for that addon and version.')
            return Response({'error': msg}, status=status.HTTP_404_NOT_FOUND)

        try:
            version = addon.versions.filter(version=version_string).latest()
        except Version.DoesNotExist:
            version = None

        serializer = FileUploadSerializer(file_upload, version=version)
        return Response(serializer.data)


class SignedFile(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @write
    def get(self, request, file_id):
        return version_views.download_file(request, file_id)
