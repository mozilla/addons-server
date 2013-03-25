from django.conf import settings

from tastypie import fields, http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse

from amo.urlresolvers import reverse
from mkt.api.authentication import (OAuthAuthentication,
                                    OwnerAuthorization)
from mkt.api.base import (MarketplaceModelResource, MarketplaceResource,
                          CORSResource)
from mkt.constants.apps import INSTALL_TYPE_USER
from users.models import UserProfile
from users.views import browserid_login


class AccountResource(MarketplaceModelResource):
    installed = fields.ListField('installed_list', readonly=True, null=True)

    class Meta:
        authentication = OAuthAuthentication()
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get', 'patch', 'put']
        fields = ['display_name']
        list_allowed_methods = []
        queryset = UserProfile.objects.filter()
        resource_name = 'settings'

    def obj_get(self, request=None, **kwargs):
        if kwargs.get('pk') == 'mine':
            kwargs['pk'] = request.amo_user.pk

        # TODO: put in acl checks for admins to get other users information.
        obj = super(AccountResource, self).obj_get(request=request, **kwargs)
        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())
        return obj

    def dehydrate_installed(self, bundle):
        # A list of the installed addons (rather than the installed_set table)
        #
        # Warning doing it this way, won't give us pagination. So less keen on
        # this, perhaps we should cap this number?
        res = (bundle.obj.installed_set.filter(install_type=INSTALL_TYPE_USER)
               .values_list('addon_id', flat=True))
        res = [reverse('api_dispatch_detail',
                       kwargs={'pk': r, 'api_name': 'apps',
                               'resource_name': 'app'})
               for r in res]
        return res


class LoginResource(CORSResource, MarketplaceResource):
    class Meta:
        resource_name = 'login'
        always_return_data = True
        list_allowed_methods = ['post']
        authorization = Authorization()

    def post_list(self, request, **kwargs):
        res = browserid_login(
            request, browserid_audience=lambda r: settings.FIREPLACE_URL)
        if res.status_code == 200:
            return self.create_response(
                request,
                {'error': None,
                 'settings': {
                        'display_name': UserProfile.objects.get(
                            user=request.user).display_name,
                        'email': request.user.email,
                        'region': 'internet',
                        }
                 })
        return r
