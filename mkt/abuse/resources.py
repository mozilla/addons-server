from tastypie import fields
from tastypie.authorization import Authorization
from tastypie.throttle import CacheThrottle

from abuse.models import AbuseReport
from mkt.api.authentication import OptionalOAuthAuthentication
from mkt.api.base import (CORSResource, GenericObject, MarketplaceResource,
                          PotatoCaptchaResource)
from mkt.api.resources import AppResource, UserProfileResource

from .forms import AppAbuseForm, UserAbuseForm


class BaseAbuseResource(PotatoCaptchaResource, CORSResource,
                        MarketplaceResource):
    """
    Base resource for abuse reports.
    """
    text = fields.CharField(attribute='text')
    ip_address = fields.CharField(attribute='ip_address', blank=True)
    reporter = fields.ForeignKey(UserProfileResource, attribute='reporter',
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

        form = self._meta.validation_form(bundle.data, request=request)
        if not form.is_valid():
            raise self.form_errors(form)

        bundle = self.full_hydrate(bundle)
        self.remove_potato(bundle)

        report = AbuseReport.objects.create(**self.rename_fields(bundle))
        report.send()

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
    user = fields.ForeignKey(UserProfileResource, attribute='user', full=True)

    class Meta(BaseAbuseResource.Meta):
        resource_name = 'user'
        validation_form = UserAbuseForm

    def hydrate_user(self, bundle):
        if 'user' in bundle.data:
            bundle.data['user'] = (self.user.to()
                                       .obj_get(pk=bundle.data['user']))
        return bundle


class AppAbuseResource(BaseAbuseResource):
    app = fields.ForeignKey(AppResource, attribute='app', full=True)

    class Meta(BaseAbuseResource.Meta):
        resource_name = 'app'
        validation_form = AppAbuseForm
        rename_field_map = BaseAbuseResource.Meta.rename_field_map + [
            ('app', 'addon'),
        ]

    def hydrate_app(self, bundle):
        if 'app' in bundle.data:
            bundle.data['app'] = self.app.to().obj_get(pk=bundle.data['app'])
        return bundle
