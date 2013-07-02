from tastypie import fields
from tastypie.authorization import Authorization
from tastypie.throttle import CacheThrottle

from abuse.models import AbuseReport
from mkt.account.api import AccountResource
from mkt.api.authentication import OptionalOAuthAuthentication
from mkt.api.base import (CORSResource, GenericObject, MarketplaceResource,
                          PotatoCaptchaResource)
from mkt.api.forms import RequestFormValidation
from mkt.api.resources import AppResource

from .forms import AppAbuseForm, UserAbuseForm


class BaseAbuseResource(PotatoCaptchaResource, CORSResource,
                        MarketplaceResource):
    """
    Base resource for abuse reports.
    """
    text = fields.CharField(attribute='text')
    ip_address = fields.CharField(attribute='ip_address', blank=True)
    reporter = fields.ForeignKey(AccountResource, attribute='reporter',
                                 null=True, full=True)

    class Meta(MarketplaceResource.Meta):
        always_return_data = True
        list_allowed_methods = ['post']
        detail_allowed_methods = []
        authentication = OptionalOAuthAuthentication()
        authorization = Authorization()
        object_class = GenericObject
        include_resource_uri = False
        validation_form = None
        rename_field_map = [
            ('text', 'message'),
        ]
        throttle = CacheThrottle(throttle_at=30)

    def obj_create(self, bundle, request=None, **kwargs):
        bundle.obj = self._meta.object_class(**kwargs)

        bundle = self.full_hydrate(bundle)
        self.remove_potato(bundle)

        AbuseReport.objects.create(**self.rename_fields(bundle)).send()

        return bundle

    def get_resource_uri(self, bundle_or_obj=None):
        """
        Noop needed to prevent NotImplementedError.
        """
        return ''

    def hydrate(self, bundle):
        """
        Add the authenticated user to the bundle.
        """
        bundle.data.update({
            'reporter': bundle.request.amo_user,
            'ip_address': bundle.request.META.get('REMOTE_ADDR', '')
        })
        return bundle

    def dehydrate(self, bundle):
        """
        Strip the `ip_address` field before presenting to the consumer.
        """
        del bundle.data['ip_address']
        return bundle

    def rename_fields(self, bundle):
        """
        Rename fields as defined in Meta.rename_field_map. Used to rename
        fields in the bundle before sending to Model.objects.create().
        """
        data = bundle.data.copy()
        for old, new in self._meta.rename_field_map:
            data[new] = data[old]
            del data[old]
        return data


class UserAbuseResource(BaseAbuseResource):
    user = fields.ForeignKey(AccountResource, attribute='user', full=True)

    class Meta(BaseAbuseResource.Meta):
        resource_name = 'user'
        validation = RequestFormValidation(form_class=UserAbuseForm)


class AppAbuseResource(BaseAbuseResource):
    app = fields.ForeignKey(AppResource, attribute='app', full=True)

    class Meta(BaseAbuseResource.Meta):
        resource_name = 'app'
        validation = RequestFormValidation(form_class=AppAbuseForm)
        rename_field_map = BaseAbuseResource.Meta.rename_field_map + [
            ('app', 'addon'),
        ]
