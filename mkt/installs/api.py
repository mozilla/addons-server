from django.core.exceptions import PermissionDenied

import commonware.log
from rest_framework.decorators import (authentication_classes,
                                       parser_classes, permission_classes)
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import cors_api_view
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.installs.forms import InstallForm
from mkt.installs.utils import install_type, record
from mkt.webapps.models import Installed

log = commonware.log.getLogger('z.api')


@cors_api_view(['POST'])
@authentication_classes([RestOAuthAuthentication,
                         RestSharedSecretAuthentication])
@parser_classes([JSONParser, FormParser])
@permission_classes([AllowAny])
def install(request):
    form = InstallForm(request.DATA, request=request)

    if form.is_valid():
        app = form.cleaned_data['app']
        type_ = install_type(request, app)

        # Users can't install non-public apps. Developers can though.
        if not app.is_public() and type_ == INSTALL_TYPE_USER:
            log.info('App not public: {0}'.format(app.pk))
            raise PermissionDenied

        if not request.amo_user:
            record(request, app)
        else:
            installed, created = Installed.objects.get_or_create(
                addon=app, user=request.amo_user, install_type=type_)
            record(request, app)
            if not created:
                return Response(status=202)

        return Response(status=201)

    return Response(status=400)
