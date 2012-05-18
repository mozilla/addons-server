import json

from tastypie import http
from tastypie.bundle import Bundle
from tastypie.resources import ModelResource
from tastypie.utils import dict_strip_unicode_keys


class MarketplaceResource(ModelResource):
    def get_resource_uri(self, bundle_or_obj):
        # Fix until my pull request gets pulled into tastypie.
        # https://github.com/toastdriven/django-tastypie/pull/490
        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        if isinstance(bundle_or_obj, Bundle):
            kwargs['pk'] = bundle_or_obj.obj.pk
        else:
            kwargs['pk'] = bundle_or_obj.pk

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name

        return self._build_reverse_url("api_dispatch_detail", kwargs=kwargs)

    def post_list(self, request, **kwargs):
        # TODO: This has to be request.META['body'] because otherwise this
        # will be empty and all the tests will fail. Boo!
        deserialized = self.deserialize(request,
                request.META.get('body', request.raw_post_data),
                format=request.META.get('CONTENT_TYPE', 'application/json'))
        # The rest is the same.
        deserialized = self.alter_deserialized_detail_data(request,
                deserialized)
        bundle = self.build_bundle(data=dict_strip_unicode_keys(deserialized),
                                   request=request)
        updated_bundle = self.obj_create(bundle, request=request,
                **self.remove_api_resource_names(kwargs))
        location = self.get_resource_uri(updated_bundle)

        if not self._meta.always_return_data:
            return http.HttpCreated(location=location)
        else:
            updated_bundle = self.full_dehydrate(updated_bundle)
            updated_bundle = self.alter_detail_data_to_serialize(request,
                updated_bundle)
            return self.create_response(request, updated_bundle,
                    response_class=http.HttpCreated,
                    location=location)

    def form_errors(self, form):
        return json.dumps({'error_message': dict(form.errors.items())})
