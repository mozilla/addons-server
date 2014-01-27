from django.http import Http404

import commonware
from rest_framework import status
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer, SerializerMethodField

import amo
import lib.iarc

from mkt.api.base import CORSMixin, SlugOrIdMixin
from mkt.developers.forms import ContentRatingForm
from mkt.webapps.models import ContentRating, Webapp
from mkt.webapps.utils import remove_iarc_exclusions


log = commonware.log.getLogger('z.devhub')


class ContentRatingSerializer(ModelSerializer):
    body_name = SerializerMethodField('get_body_name')
    body_slug = SerializerMethodField('get_body_slug')

    name = SerializerMethodField('get_rating_name')
    slug = SerializerMethodField('get_rating_slug')
    description = SerializerMethodField('get_rating_description')

    def get_body_name(self, obj):
        return obj.get_body().name

    def get_body_slug(self, obj):
        return obj.get_body().label

    def get_rating_name(self, obj):
        return obj.get_rating().name

    def get_rating_slug(self, obj):
        return obj.get_rating().label

    def get_rating_description(self, obj):
        return obj.get_rating().description

    class Meta:
        model = ContentRating
        fields = ('id', 'created', 'modified', 'body_name', 'body_slug',
                  'name', 'slug', 'description')


class ContentRatingList(CORSMixin, SlugOrIdMixin, ListAPIView):
    model = ContentRating
    serializer_class = ContentRatingSerializer
    permission_classes = (AllowAny,)
    cors_allowed_methods = ['get']

    queryset = Webapp.objects.all()
    slug_field = 'app_slug'

    def get(self, request, *args, **kwargs):
        app = self.get_object()

        self.queryset = app.content_ratings.all()

        if 'since' in request.GET:
            form = ContentRatingForm(request.GET)
            if form.is_valid():
                self.queryset = self.queryset.filter(
                    modified__gt=form.cleaned_data['since'])

        if not self.queryset.exists():
            raise Http404()

        return super(ContentRatingList, self).get(self, request)


class ContentRatingsPingback(CORSMixin, SlugOrIdMixin, CreateAPIView):
    cors_allowed_methods = ['post']
    parser_classes = (lib.iarc.utils.IARC_JSON_Parser,)
    permission_classes = (AllowAny,)

    queryset = Webapp.objects.all()
    slug_field = 'app_slug'

    def post(self, request, pk, *args, **kwargs):
        log.info(u'Received IARC pingback for app:%s' % pk)

        if request.content_type != 'application/json':
            log.info(u'IARC pingback not of content-type "application/json"')
            return Response({
                'detail': "Endpoint only accepts 'application/json'."
            }, status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

        app = self.get_object()

        # Verify token.
        data = request.DATA[0]
        if app.iarc_token() != data.get('token'):
            log.info(u'Token mismatch in IARC pingback for app:%s' % app.id)
            return Response({'detail': 'Token mismatch'},
                            status=status.HTTP_400_BAD_REQUEST)

        if data.get('ratings'):
            log.info(u'Setting content ratings from IARC pingback for app:%s' %
                     app.id)
            # We found a rating, so store the id and code for future use.
            if 'submission_id' in data and 'security_code' in data:
                app.set_iarc_info(data['submission_id'], data['security_code'])

            # Update status if incomplete status.
            # Do this before set_content_ratings to not prematurely trigger
            # a refresh.
            log.info('Checking app:%s completeness after IARC pingback.'
                     % app.id)
            if (app.has_incomplete_status() and
                app.is_fully_complete(ignore_ratings=True)):
                log.info('Updating app status from IARC pingback for app:%s' %
                         app.id)
                # Don't call update to prevent recursion in update_status.
                app.update(status=amo.STATUS_PENDING)
            elif app.has_incomplete_status():
                log.info('Reasons for app:%s incompleteness after IARC '
                         'pingback: %s' % (app.id, app.completion_errors()))

            app.set_descriptors(data.get('descriptors', []))
            app.set_interactives(data.get('interactives', []))
            # Set content ratings last since it triggers a refresh on Content
            # Ratings page. We want descriptors and interactives visible by
            # the time it's refreshed.
            app.set_content_ratings(data.get('ratings', {}))

            remove_iarc_exclusions(app)

        return Response('ok')
