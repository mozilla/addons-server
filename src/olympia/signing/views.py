import functools

from django import forms
from django.utils.translation import ugettext

from rest_framework import exceptions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon
from olympia.amo.decorators import use_primary_db
from olympia.amo.urlresolvers import reverse
from olympia.api.authentication import JWTKeyAuthentication
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.throttling import (
    GranularIPRateThrottle, GranularUserRateThrottle,
    ThrottleOnlyUnsafeMethodsMixin
)
from olympia.blocklist.models import Block
from olympia.devhub.views import handle_upload as devhub_handle_upload
from olympia.devhub.permissions import IsSubmissionAllowedFor
from olympia.files.models import FileUpload
from olympia.files.utils import parse_addon
from olympia.signing.serializers import FileUploadSerializer
from olympia.versions import views as version_views
from olympia.versions.models import Version


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
                addon = Addon.unfiltered.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    msg = ugettext(
                        'Could not find Add-on with ID "{}".').format(guid)
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


class BurstUserAddonUploadThrottle(
        ThrottleOnlyUnsafeMethodsMixin, GranularUserRateThrottle):
    scope = 'burst_user_addon_upload'
    rate = '3/minute'


class SustainedUserAddonUploadThrottle(
        ThrottleOnlyUnsafeMethodsMixin, GranularUserRateThrottle):
    scope = 'sustained_user_addon_upload'
    rate = '20/hour'


class BurstIPAddonUploadThrottle(
        ThrottleOnlyUnsafeMethodsMixin, GranularIPRateThrottle):
    scope = 'burst_ip_addon_upload'
    rate = '6/minute'


class SustainedIPAddonUploadThrottle(
        ThrottleOnlyUnsafeMethodsMixin, GranularIPRateThrottle):
    scope = 'sustained_ip_addon_upload'
    rate = '50/hour'


class VersionView(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated, IsSubmissionAllowedFor]
    throttle_classes = (
        BurstUserAddonUploadThrottle, SustainedUserAddonUploadThrottle,
        BurstIPAddonUploadThrottle, SustainedIPAddonUploadThrottle,
    )

    def check_throttles(self, request):
        # Let users with LanguagePack:Submit permission bypass throttles.
        # Used by releng automated signing scripts so that they can sign a
        # bunch of langpacks at once.
        if acl.action_allowed(request, amo.permissions.LANGPACK_SUBMIT):
            return
        super().check_throttles(request)

    # When DRF 3.12 is released, we can remove the custom check_permissions()
    # and permission_denied() as it will contain the fix for
    # https://github.com/encode/django-rest-framework/issues/7038
    def check_permissions(self, request):
        """
        Check if the request should be permitted.
        Raises an appropriate exception if the request is not permitted.

        (Lifted from DRF, but also passing the code argument down to the
        permission_denied() call if that property existed on the failed
        permission class)
        """
        for permission in self.get_permissions():
            if not permission.has_permission(request, self):
                self.permission_denied(
                    request, message=getattr(permission, 'message', None),
                    code=getattr(permission, 'code', None),
                )

    def permission_denied(self, request, message=None, code=None):
        """
        If request is not permitted, determine what kind of exception to raise.

        (Lifted from DRF, but also passing the optional code argument to
        the PermissionDenied exception)
        """
        if request.authenticators and not request.successful_authenticator:
            raise exceptions.NotAuthenticated()
        raise exceptions.PermissionDenied(
            detail=message, code=code)

    def post(self, request, *args, **kwargs):
        version_string = request.data.get('version', None)

        try:
            file_upload, _ = self.handle_upload(request, None, version_string)
        except forms.ValidationError as exc:
            return Response(
                {'error': exc.message},
                status=exc.code or status.HTTP_400_BAD_REQUEST)

        serializer = FileUploadSerializer(
            file_upload, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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

        serializer = FileUploadSerializer(
            file_upload, context={'request': request})
        return Response(serializer.data, status=status_code)

    @use_primary_db
    def handle_upload(self, request, addon, version_string, guid=None):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            raise forms.ValidationError(
                ugettext(u'Missing "upload" key in multipart file data.'),
                status.HTTP_400_BAD_REQUEST)

        # Parse the file to get and validate package data with the addon.
        parsed_data = parse_addon(filedata, addon, user=request.user)

        if addon is not None and addon.status == amo.STATUS_DISABLED:
            msg = ugettext(
                'You cannot add versions to an addon that has status: %s.'
                % amo.STATUS_CHOICES_ADDON[amo.STATUS_DISABLED])
            raise forms.ValidationError(msg, status.HTTP_400_BAD_REQUEST)

        version_string = version_string or parsed_data['version']

        if version_string and parsed_data['version'] != version_string:
            raise forms.ValidationError(
                ugettext('Version does not match the manifest file.'),
                status.HTTP_400_BAD_REQUEST)

        existing_version = addon and Version.unfiltered.filter(
            addon=addon, version=version_string)
        if existing_version:
            latest_version = addon.find_latest_version(None, exclude=())
            msg = ugettext('Version already exists. Latest version is: %s.'
                           % latest_version.version)
            raise forms.ValidationError(msg, status.HTTP_409_CONFLICT)

        package_guid = parsed_data.get('guid', None)

        dont_allow_no_guid = (
            not addon and not package_guid and
            not parsed_data.get('is_webextension', False))

        if dont_allow_no_guid:
            raise forms.ValidationError(
                ugettext(
                    'Only WebExtensions are allowed to omit the Add-on ID'),
                status.HTTP_400_BAD_REQUEST)

        if guid is not None and not addon and not package_guid:
            # No guid was present in the package, but one was provided in the
            # URL, so we take it instead of generating one ourselves. There is
            # an extra validation check for those: guids passed in the URL are
            # not allowed to be longer than 64 chars.
            if len(guid) > 64:
                raise forms.ValidationError(ugettext(
                    'Please specify your Add-on ID in the manifest if it\'s '
                    'longer than 64 characters.'
                ))

            parsed_data['guid'] = guid
        elif not guid and package_guid:
            guid = package_guid

        if guid:
            # If we did get a guid, regardless of its source, validate it now
            # before creating anything.
            if not amo.ADDON_GUID_PATTERN.match(guid):
                raise forms.ValidationError(
                    ugettext('Invalid Add-on ID in URL or package'),
                    status.HTTP_400_BAD_REQUEST)

        block_qs = Block.objects.filter(guid=addon.guid if addon else guid)
        if block_qs and block_qs.first().is_version_blocked(version_string):
            msg = ugettext(
                'Version {version} matches {block_url} for this add-on. '
                'You can contact {amo_admins} for additional information.')
            raise forms.ValidationError(
                msg.format(
                    version=version_string,
                    block_url=absolutify(
                        reverse('blocklist.block', args=[guid])),
                    amo_admins='amo-admins@mozilla.com'),
                status.HTTP_400_BAD_REQUEST)

        # channel will be ignored for new addons.
        if addon is None:
            channel = amo.RELEASE_CHANNEL_UNLISTED  # New is always unlisted.
            addon = Addon.initialize_addon_from_upload(
                data=parsed_data, upload=filedata, channel=channel,
                user=request.user)
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

            if (addon.disabled_by_user and
                    channel == amo.RELEASE_CHANNEL_LISTED):
                msg = ugettext(
                    'You cannot add listed versions to an addon set to '
                    '"Invisible" state.')
                raise forms.ValidationError(msg, status.HTTP_400_BAD_REQUEST)

            will_have_listed = channel == amo.RELEASE_CHANNEL_LISTED
            if not addon.has_complete_metadata(
                    has_listed_versions=will_have_listed):
                raise forms.ValidationError(
                    ugettext('You cannot add a listed version to this addon '
                             'via the API due to missing metadata. '
                             'Please submit via the website'),
                    status.HTTP_400_BAD_REQUEST)

        file_upload = devhub_handle_upload(
            filedata=filedata, request=request, addon=addon, submit=True,
            channel=channel, source=amo.UPLOAD_SOURCE_API)

        return file_upload, created

    @use_primary_db
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

        serializer = FileUploadSerializer(
            file_upload, version=version, context={'request': request})
        return Response(serializer.data)


class SignedFile(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @use_primary_db
    def get(self, request, file_id):
        return version_views.download_file(request, file_id)
