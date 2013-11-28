import commonware.log
from rest_framework import mixins
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import (HTTP_201_CREATED, HTTP_202_ACCEPTED,
                                   HTTP_400_BAD_REQUEST)
from rest_framework.viewsets import GenericViewSet
from tastypie import fields, http
from tastypie.resources import ALL_WITH_RELATIONS

import amo
from addons.models import Addon, Preview
from files.models import FileUpload

from mkt.api.authentication import (OAuthAuthentication,
                                    RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import (AllowAppOwner, AppOwnerAuthorization,
                                   OwnerAuthorization)
from mkt.api.base import (CORSMixin, CORSResource, http_error,
                          MarketplaceModelResource)
from mkt.api.forms import NewPackagedForm, PreviewArgsForm, PreviewJSONForm
from mkt.developers import tasks
from mkt.developers.forms import NewManifestForm, PreviewForm
from mkt.submit.serializers import AppStatusSerializer, FileUploadSerializer
from mkt.webapps.models import Webapp


log = commonware.log.getLogger('z.api')


class ValidationViewSet(CORSMixin, mixins.CreateModelMixin,
                        mixins.RetrieveModelMixin, GenericViewSet):
    cors_allowed_methods = ['get', 'post']
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication,
                              RestAnonymousAuthentication]
    permission_classes = [AllowAny]
    model = FileUpload
    serializer_class = FileUploadSerializer

    def create(self, request, *args, **kwargs):
        """
        Custom create method allowing us to re-use form logic and distinguish
        packaged app from hosted apps, applying delays to the validation task
        if necessary.

        Doesn't rely on any serializer, just forms.
        """
        data = self.request.DATA
        packaged = 'upload' in data
        form = (NewPackagedForm(data) if packaged
                else NewManifestForm(data))

        if not form.is_valid():
            return Response(form.errors, status=HTTP_400_BAD_REQUEST)

        if not packaged:
            upload = FileUpload.objects.create(
                user=getattr(request, 'amo_user', None))
            # The hosted app validator is pretty fast.
            tasks.fetch_manifest(form.cleaned_data['manifest'], upload.pk)
        else:
            upload = form.file_upload
            # The packaged app validator is much heavier.
            tasks.validator.delay(upload.pk)

        log.info('Validation created: %s' % upload.pk)
        self.kwargs = {'pk': upload.pk}
        # Re-fetch the object, fetch_manifest() might have altered it.
        upload = self.get_object()
        serializer = self.get_serializer(upload)
        status = HTTP_201_CREATED if upload.processed else HTTP_202_ACCEPTED
        return Response(serializer.data, status=status)


class StatusViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    GenericViewSet):
    queryset = Webapp.objects.all()
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [AllowAppOwner]
    serializer_class = AppStatusSerializer

    def update(self, request, *args, **kwargs):
        # PUT is disallowed, only PATCH is accepted for this endpoint.
        if request.method == 'PUT':
            raise MethodNotAllowed('PUT')
        return super(StatusViewSet, self).update(request, *args, **kwargs)


class PreviewResource(CORSResource, MarketplaceModelResource):
    image_url = fields.CharField(attribute='image_url', readonly=True)
    thumbnail_url = fields.CharField(attribute='thumbnail_url', readonly=True)

    class Meta(MarketplaceModelResource.Meta):
        queryset = Preview.objects.all()
        list_allowed_methods = ['post']
        allowed_methods = ['get', 'delete']
        always_return_data = True
        fields = ['id', 'filetype']
        authentication = OAuthAuthentication()
        authorization = OwnerAuthorization()
        resource_name = 'preview'
        filtering = {'addon': ALL_WITH_RELATIONS}

    def obj_create(self, bundle, request, **kwargs):
        # Ensure that people don't pass strings through.
        args = PreviewArgsForm(request.GET)
        if not args.is_valid():
            raise self.form_errors(args)

        addon = self.get_object_or_404(Addon,
                                       pk=args.cleaned_data['app'],
                                       type=amo.ADDON_WEBAPP)
        if not AppOwnerAuthorization().is_authorized(request, object=addon):
            raise http_error(http.HttpForbidden,
                             'You are not an author of that app.')

        data_form = PreviewJSONForm(bundle.data)
        if not data_form.is_valid():
            raise self.form_errors(data_form)

        form = PreviewForm(data_form.cleaned_data)
        if not form.is_valid():
            raise self.form_errors(form)

        form.save(addon)
        bundle.obj = form.instance
        log.info('Preview created: %s' % bundle.obj.pk)
        return bundle

    def obj_delete(self, request, **kwargs):
        obj = self.get_by_resource_or_404(request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request,
                                                     object=obj.addon):
            raise http_error(http.HttpForbidden,
                             'You are not an author of that app.')

        log.info('Preview deleted: %s' % obj.pk)
        return super(PreviewResource, self).obj_delete(request, **kwargs)

    def obj_get(self, request=None, **kwargs):
        obj = super(PreviewResource, self).obj_get(request=request, **kwargs)
        if not AppOwnerAuthorization().is_authorized(request,
                                                     object=obj.addon):
            raise http_error(http.HttpForbidden,
                             'You are not an author of that app.')

        log.info('Preview retreived: %s' % obj.pk)
        return obj

    def dehydrate(self, bundle):
        # Returning an image back to the user isn't useful, let's stop that.
        if 'file' in bundle.data:
            del bundle.data['file']
        return bundle
