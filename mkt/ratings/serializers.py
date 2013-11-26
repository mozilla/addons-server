from django.core.urlresolvers import reverse

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from reviews.models import Review, ReviewFlag

from mkt.account.serializers import AccountSerializer
from mkt.api.fields import SlugOrPrimaryKeyRelatedField, SplitField
from mkt.api.exceptions import Conflict
from mkt.regions import REGIONS_DICT, get_region
from mkt.versions.api import SimpleVersionSerializer
from mkt.webapps.models import Webapp


class RatingSerializer(serializers.ModelSerializer):
    app = SplitField(
        SlugOrPrimaryKeyRelatedField(slug_field='app_slug',
                                     queryset=Webapp.objects.all(),
                                     source='addon'),
        serializers.HyperlinkedRelatedField(view_name='app-detail',
                                            read_only=True, source='addon'))
    body = serializers.CharField()
    user = AccountSerializer(read_only=True)
    report_spam = serializers.SerializerMethodField('get_report_spam_link')
    resource_uri = serializers.HyperlinkedIdentityField(
        view_name='ratings-detail')
    is_author = serializers.SerializerMethodField('get_is_author')
    has_flagged = serializers.SerializerMethodField('get_has_flagged')
    version = SimpleVersionSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ('app', 'body', 'created', 'has_flagged', 'is_author',
                  'modified', 'rating', 'report_spam', 'resource_uri', 'user',
                  'version')

    def __init__(self, *args, **kwargs):
        super(RatingSerializer, self).__init__(*args, **kwargs)
        if 'request' in self.context:
            self.request = self.context['request']
        else:
            self.request = None

        if not self.request or not self.request.amo_user:
            self.fields.pop('is_author')
            self.fields.pop('has_flagged')

        if self.request and self.request.method in ('PUT', 'PATCH'):
            # Don't let users modify 'app' field at edit time
            self.fields['app'].read_only = True

    def get_report_spam_link(self, obj):
        return reverse('ratings-flag', kwargs={'pk': obj.pk})

    def get_is_author(self, obj):
        return obj.user.pk == self.request.amo_user.pk

    def get_has_flagged(self, obj):
        return (not self.get_is_author(obj) and
                obj.reviewflag_set.filter(user=self.request.amo_user).exists())

    def validate(self, attrs):
        if not getattr(self, 'object'):
            # If we are creating a rating, then we need to do various checks on
            # the app. Because these checks need the version as well, we have
            # to do them here and not in validate_app().

            # Assign user and ip_address. It won't change once the review is
            # created.
            attrs['user'] = self.request.amo_user
            attrs['ip_address'] = self.request.META.get('REMOTE_ADDR', '')

            # If the app is packaged, add in the current version.
            if attrs['addon'].is_packaged:
                attrs['version'] = attrs['addon'].current_version

            # Return 409 if the user has already reviewed this app.
            app = attrs['addon']
            amo_user = self.request.amo_user
            qs = self.context['view'].queryset.filter(addon=app, user=amo_user)
            if app.is_packaged:
                qs = qs.filter(version=attrs['version'])
            if qs.exists():
                raise Conflict('You have already reviewed this app.')

            # Return 403 is the app is not public.
            if not app.is_public():
                raise PermissionDenied('The app requested is not public.')

            # Return 403 if the user is attempting to review their own app.
            if app.has_author(amo_user):
                raise PermissionDenied('You may not review your own app.')

            # Return 403 if not a free app and the user hasn't purchased it.
            if app.is_premium() and not app.is_purchased(amo_user):
                raise PermissionDenied("You may not review paid apps you "
                                       "haven't purchased.")

            # Return 403 if the app is not available in the current region.
            current_region = get_region()
            if not app.listed_in(region=REGIONS_DICT[current_region]):
                raise PermissionDenied('App not available in region "%s".' %
                                       current_region)

        return attrs

    def validate_app(self, attrs, source):
        # Don't allow users to change the app on an existing rating.
        if getattr(self, 'object'):
            attrs[source] = self.object.addon
        return attrs


class RatingFlagSerializer(serializers.ModelSerializer):
    user = serializers.Field()
    review_id = serializers.Field()

    class Meta:
        model = ReviewFlag
        fields = ('review_id', 'flag', 'note', 'user')

    def validate(self, attrs):
        attrs['user'] = self.context['request'].amo_user
        attrs['review_id'] = self.context['view'].kwargs['review']
        if 'note' in attrs and attrs['note'].strip():
            attrs['flag'] = ReviewFlag.OTHER
        if ReviewFlag.objects.filter(review_id=attrs['review_id'],
                                     user=attrs['user']).exists():
            raise Conflict('You have already flagged this review.')
        return attrs
