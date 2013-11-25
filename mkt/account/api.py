from rest_framework.generics import ListAPIView

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowSelf
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.api import AppSerializer
from mkt.webapps.models import Webapp


class InstalledView(ListAPIView):
    serializer_class = AppSerializer
    permission_classes = [AllowSelf]
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    def get_queryset(self):
        return  Webapp.objects.no_cache().filter(
            installed__user=self.request.amo_user,
            installed__install_type=INSTALL_TYPE_USER)
