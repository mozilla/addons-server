import logging

from django import forms

from rest_framework import status
from rest_framework.response import Response
from tower import ugettext as _

import amo
from access import acl
from addons.models import Addon
from api.jwt_auth.views import JWTProtectedView
from devhub.views import handle_upload
from files.models import FileUpload
from files.utils import parse_addon
from versions import views as version_views
from versions.models import Version
from signing.serializers import FileUploadSerializer

log = logging.getLogger('signing')


def with_addon(allow_missing=False):
    """Call the view function with an addon instead of a guid. This will try
    find an addon with the guid and verify the user's permissions. If the
    add-on is not found it will 404 when allow_missing is False otherwise it
    will call the view with addon set to None."""
    def wrapper(fn):
        def inner(view, request, guid=None, **kwargs):
            try:
                addon = Addon.unfiltered.get(guid=guid)
            except Addon.DoesNotExist:
                if allow_missing:
                    addon = None
                else:
                    return Response({'error': _('Could not find addon.')},
                                    status=status.HTTP_404_NOT_FOUND)
            if addon is not None and not addon.has_author(request.user):
                return Response(
                    {'error': _('You do not own this addon.')},
                    status=status.HTTP_403_FORBIDDEN)
            return fn(view, request, addon=addon, **kwargs)
        return inner
    return wrapper


class VersionView(JWTProtectedView):

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
                    _(u'You cannot submit this type of add-ons'))
        except forms.ValidationError as e:
            return Response({'error': e.message},
                            status=status.HTTP_400_BAD_REQUEST)
        if pkg['version'] != version_string:
            return Response(
                {'error': _('Version does not match install.rdf.')},
                status=status.HTTP_400_BAD_REQUEST)
        elif (addon is not None and
                addon.versions.filter(
                    version=version_string,
                    files__status__in=amo.REVIEWED_STATUSES).exists()):
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

    @with_addon()
    def get(self, request, addon, version_string, pk=None):
        file_upload_qs = FileUpload.objects.filter(
            addon=addon, version=version_string)
        try:
            if pk is None:
                file_upload = file_upload_qs.latest()
                log.info('getting latest upload for {addon} {version}: '
                         '{file_upload.pk}'.format(
                             addon=addon, version=version_string,
                             file_upload=file_upload))
            else:
                file_upload = file_upload_qs.get(pk=pk)
                log.info('getting specific upload for {addon} {version} {pk}: '
                         '{file_upload.pk}'.format(
                             addon=addon, version=version_string, pk=pk,
                             file_upload=file_upload))
        except FileUpload.DoesNotExist:
            return Response(
                {'error': _('No uploaded file for that addon and version.')},
                status=status.HTTP_404_NOT_FOUND)

        try:
            version = addon.versions.get(version=version_string)
        except Version.DoesNotExist:
            version = None

        serializer = FileUploadSerializer(file_upload, version=version)
        return Response(serializer.data)


class SignedFile(JWTProtectedView):

    def get(self, request, file_id):
        return version_views.download_file(request, file_id)
