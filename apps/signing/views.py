from django import forms

from rest_framework import status
from rest_framework.response import Response
from tower import ugettext as _

from api.jwt_auth.views import JWTProtectedView
from addons.models import Addon
from devhub.views import handle_upload
from files.utils import parse_addon


class UploadAddonView(JWTProtectedView):

    def put(self, request, guid, version):
        try:
            addon = Addon.unfiltered.get(guid=guid)
        except Addon.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not addon.has_author(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            filedata = request.FILES['upload']
        except KeyError:
            return Response({"error": "No 'upload' file found."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Verify that the guid and version match.
        try:
            pkg = parse_addon(filedata, addon)
        except forms.ValidationError as e:
            return Response({"error": e.message},
                            status=status.HTTP_400_BAD_REQUEST)
        if pkg['version'] != version:
            return Response(
                {"error": _("Version does not match install.rdf.")},
                status=status.HTTP_400_BAD_REQUEST)
        elif addon.versions.filter(version=version).exists():
            return Response({"error": _("Version already exists.")},
                            status=status.HTTP_409_CONFLICT)

        file_upload = handle_upload(
            filedata=filedata, user=request.user, addon=addon, submit=True)

        return Response({'id': file_upload.pk})
