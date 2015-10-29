from django import forms

from rest_framework import status
from rest_framework.response import Response
from tower import ugettext as _

from addons.models import Addon
from api.jwt_auth.views import JWTProtectedView
from devhub.views import handle_upload
from files.models import FileUpload
from files.utils import parse_addon
from versions.models import Version
from signing.serializers import FileUploadSerializer


def with_addon(fn):
    def inner(view, request, guid, version):
        try:
            addon = Addon.unfiltered.get(guid=guid)
        except Addon.DoesNotExist:
            return Response({'error': _('Could not find addon.')},
                            status=status.HTTP_404_NOT_FOUND)
        if not addon.has_author(request.user):
            return Response(
                {'error': _('You do not own this addon.')},
                status=status.HTTP_403_FORBIDDEN)
        return fn(view, request, addon, version)
    return inner


class VersionView(JWTProtectedView):

    @with_addon
    def put(self, request, addon, version):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            return Response(
                {'error': _('Missing "upload" key in multipart file data.')},
                status=status.HTTP_400_BAD_REQUEST)

        try:
            # Parse the file to get and validate package data with the addon.
            pkg = parse_addon(filedata, addon)
        except forms.ValidationError as e:
            return Response({'error': e.message},
                            status=status.HTTP_400_BAD_REQUEST)
        if pkg['version'] != version:
            return Response(
                {'error': _('Version does not match install.rdf.')},
                status=status.HTTP_400_BAD_REQUEST)
        elif addon.versions.filter(version=version).exists():
            return Response({'error': _('Version already exists.')},
                            status=status.HTTP_409_CONFLICT)

        file_upload = handle_upload(
            filedata=filedata, user=request.user, addon=addon, submit=True)

        return Response(FileUploadSerializer(file_upload).data,
                        status=status.HTTP_202_ACCEPTED)

    @with_addon
    def get(self, request, addon, version):
        try:
            file_upload = FileUpload.objects.get(addon=addon, version=version)
        except FileUpload.DoesNotExist:
            return Response(
                {'error': _('No uploaded file for that addon and version.')},
                status=status.HTTP_404_NOT_FOUND)

        try:
            version_obj = addon.versions.get(version=version)
        except Version.DoesNotExist:
            version_obj = None

        serializer = FileUploadSerializer(file_upload, version=version_obj)
        return Response(serializer.data)
