import functools
import logging

from django import forms
from django.conf import settings

from rest_framework import status
from rest_framework.response import Response
from tower import ugettext as _

from access import acl
from addons.models import Addon
from amo.decorators import use_master
from api.jwt_auth.views import JWTProtectedView
from devhub.views import handle_upload
from files.models import FileUpload
from files.utils import parse_addon
from versions import views as version_views
from versions.models import Version
from signing.serializers import FileUploadSerializer

log = logging.getLogger('signing')


def handle_read_only_mode(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        if settings.READ_ONLY:
            return Response(
                {'error': _("Some features are temporarily disabled while we "
                            "perform website maintenance. We'll be back to "
                            "full capacity shortly.")},
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
        def inner(view, request, guid=None, **kwargs):
            try:
                addon = Addon.unfiltered.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    return Response({'error': _('Could not find add-on with '
                                                'id "{}".').format(guid)},
                                    status=status.HTTP_404_NOT_FOUND)
            # Call the view if there is no add-on, the current user is an
            # auther of the add-on or the current user is an admin and the
            # request is a GET.
            if addon is None or (
                    addon.has_author(request.user)
                    or (request.method == 'GET'
                        and acl.action_allowed_user(request.user, 'Addons',
                                                    'Edit'))):
                return fn(view, request, addon=addon, **kwargs)
            else:
                return Response(
                    {'error': _('You do not own this addon.')},
                    status=status.HTTP_403_FORBIDDEN)
        return inner
    return wrapper


class VersionView(JWTProtectedView):

    @handle_read_only_mode
    @with_addon(allow_missing=True)
    def put(self, request, addon, version_string):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            return Response(
                {'error': _('Missing "upload" key in multipart file data.')},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse the file to get and validate package data with the addon.
            pkg = parse_addon(filedata, addon)
            if not acl.submission_allowed(request.user, pkg):
                raise forms.ValidationError(
                    _(u'You cannot submit this type of add-on'))
        except forms.ValidationError as e:
            return Response({'error': e.message},
                            status=status.HTTP_400_BAD_REQUEST)
        if pkg['version'] != version_string:
            return Response(
                {'error': _('Version does not match install.rdf.')},
                status=status.HTTP_400_BAD_REQUEST)
        elif (addon is not None and
                addon.versions.filter(version=version_string).exists()):
            return Response({'error': _('Version already exists.')},
                            status=status.HTTP_409_CONFLICT)

        if addon is None:
            addon = Addon.create_addon_from_upload_data(
                data=pkg, user=request.user, is_listed=False)
            status_code = status.HTTP_201_CREATED
        else:
            status_code = status.HTTP_202_ACCEPTED

        file_upload = handle_upload(
            filedata=filedata, user=request.user, addon=addon, submit=True)

        return Response(FileUploadSerializer(file_upload).data,
                        status=status_code)

    @use_master
    @with_addon()
    def get(self, request, addon, version_string, uuid=None):
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
            return Response(
                {'error': _('No uploaded file for that addon and version.')},
                status=status.HTTP_404_NOT_FOUND)

        try:
            version = addon.versions.filter(version=version_string).latest()
        except Version.DoesNotExist:
            version = None

        serializer = FileUploadSerializer(file_upload, version=version)
        return Response(serializer.data)


class SignedFile(JWTProtectedView):

    @use_master
    def get(self, request, file_id):
        return version_views.download_file(request, file_id)
