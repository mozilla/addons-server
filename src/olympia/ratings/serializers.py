import re

from collections import OrderedDict
from urllib.parse import unquote

from django.utils.translation import ugettext

from bleach.linkifier import TLDS
from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from olympia.accounts.serializers import BaseUserSerializer
from olympia.addons.serializers import (
    SimpleAddonSerializer, SimpleVersionSerializer)
from olympia.api.utils import is_gate_active
from olympia.ratings.models import Rating, RatingFlag, RatingVote, GroupedVoting
from olympia.versions.models import Version

# This matches the following three types of patterns:
# http://... or https://..., generic domain names, and IPv4 octets. It does not
# match IPv6 addresses or long strings such as "example dot com".
link_pattern = re.compile(
    r'((://)|'  # Protocols (e.g.: http://)
    r'((\d{1,3}\.){3}(\d{1,3}))|'
    r'([0-9a-z\-%%]+\.(%s)))' % '|'.join(TLDS),
    (re.I | re.U | re.M))


class RatingAddonSerializer(SimpleAddonSerializer):
    def get_attribute(self, obj):
        # Avoid database queries if possible by re-using the addon object from
        # the view if there is one.
        return self.context['view'].get_addon_object() or obj.addon


class BaseRatingSerializer(serializers.ModelSerializer):
    addon = RatingAddonSerializer(read_only=True)
    body = serializers.CharField(allow_null=True, required=False)
    is_deleted = serializers.BooleanField(read_only=True, source='deleted')
    is_developer_reply = serializers.SerializerMethodField()
    is_latest = serializers.BooleanField(read_only=True)
    previous_count = serializers.IntegerField(read_only=True)
    user = BaseUserSerializer(read_only=True)
    flags = serializers.SerializerMethodField()
    votes = serializers.SerializerMethodField()

    class Meta:
        model = Rating
        fields = ('id', 'addon', 'body', 'created', 'flags', 'votes', 'is_deleted',
                  'is_developer_reply', 'is_latest', 'previous_count', 'user')

    def __init__(self, *args, **kwargs):
        super(BaseRatingSerializer, self).__init__(*args, **kwargs)
        self.request = kwargs.get('context', {}).get('request')

    def get_is_developer_reply(self, obj):
        return obj.reply_to_id is not None

    def validate(self, data):
        data = super(BaseRatingSerializer, self).validate(data)
        request = self.context['request']

        data['user_responsible'] = request.user

        # There are a few fields that need to be set at creation time and never
        # modified afterwards:
        if not self.partial:
            # Because we want to avoid extra queries, addon is a
            # SerializerMethodField, which means it needs to be validated
            # manually. Fortunately the view does most of the work for us.
            data['addon'] = self.context['view'].get_addon_object()
            if data['addon'] is None:
                raise serializers.ValidationError(
                    {'addon': ugettext('This field is required.')})

            # Get the user from the request, don't allow clients to pick one
            # themselves.
            data['user'] = request.user

            # Also include the user ip adress.
            data['ip_address'] = request.META.get('REMOTE_ADDR', '')
        else:
            # When editing, you can't change the add-on.
            if self.context['request'].data.get('addon'):
                raise serializers.ValidationError(
                    {'addon': ugettext(
                        u'You can\'t change the add-on of a review once'
                        u' it has been created.')})

        # Clean up body and automatically flag the review if an URL was in it.
        body = data.get('body', '')
        if body:
            if '<br>' in body:
                data['body'] = re.sub('<br>', '\n', body)
            # Unquote the body when searching for links, in case someone tries
            # 'example%2ecom'.
            if link_pattern.search(unquote(body)) is not None:
                data['flag'] = True
                data['editorreview'] = True

        return data

    def get_flags(self, obj):
        if self.context['view'].should_include_flags():
            # should be maximum one RatingFlag per rating+user anyway.
            rating_flags = obj.ratingflag_set.filter(
                user=self.context['request'].user)
            return [
                {'flag': flag.flag, 'note': flag.note or None}
                for flag in rating_flags]
        return None

    def get_votes(self, obj):
        if self.context['view'].should_include_votes():
            # if we only specify rating id (Detail display)
            if 'addon' not in self.context['request'].query_params:
                rating_votes = GroupedVoting.get(obj.addon.pk, obj.id)
                return {
                    'upvote': rating_votes[1][1], 'downvote': rating_votes[0][1]}
            else:
            # if we specify addon id (List ratings display)
                rating_votes = GroupedVoting.get(
                    self.context['request'].query_params['addon'], obj.pk)
                return {
                    'upvote': rating_votes[1][1], 'downvote': rating_votes[0][1]}
        return None

    def to_representation(self, instance):
        out = super(BaseRatingSerializer, self).to_representation(instance)
        if self.request and is_gate_active(self.request, 'ratings-title-shim'):
            out['title'] = None
        if not self.context['view'].should_include_flags():
            out.pop('flags', None)
        if not self.context['view'].should_include_votes():
            out.pop('votes', None)
        return out


class RatingSerializerReply(BaseRatingSerializer):
    """Serializer used for replies only."""
    body = serializers.CharField(
        allow_null=False, required=True, allow_blank=False)

    def to_representation(self, obj):
        should_access_deleted = getattr(
            self.context['view'], 'should_access_deleted_ratings', False)
        if obj.deleted and not should_access_deleted:
            return None
        return super(RatingSerializerReply, self).to_representation(obj)

    def validate(self, data):
        # rating_object is set on the view by the reply() method.
        data['reply_to'] = self.context['view'].rating_object

        # When a reply is made on top of an existing deleted reply, we make
        # an edit instead, so we need to make sure `deleted` is reset.
        data['deleted'] = False

        if data['reply_to'].reply_to:
            # Only one level of replying is allowed, so if it's already a
            # reply, we shouldn't allow that.
            msg = ugettext(
                u'You can\'t reply to a review that is already a reply.')
            raise serializers.ValidationError(msg)

        data = super(RatingSerializerReply, self).validate(data)
        return data


class RatingVersionSerializer(SimpleVersionSerializer):
    class Meta:
        model = Version
        fields = ('id', 'version')

    def to_internal_value(self, data):
        """Resolve the version only by `id`."""
        # Version queryset is unfiltered, the version is checked more
        # thoroughly in `RatingSerializer.validate()` method.
        field = PrimaryKeyRelatedField(queryset=Version.unfiltered)
        value = field.to_internal_value(data)
        return OrderedDict([('id', data), ('version', value)])


class RatingSerializer(BaseRatingSerializer):
    reply = RatingSerializerReply(read_only=True)
    version = RatingVersionSerializer()
    score = serializers.IntegerField(min_value=1, max_value=5, source='rating')

    class Meta:
        model = Rating
        fields = BaseRatingSerializer.Meta.fields + (
            'score', 'reply', 'version')

    def __init__(self, *args, **kwargs):
        super(RatingSerializer, self).__init__(*args, **kwargs)
        score_to_rating = (
                self.request and
                is_gate_active(self.request, 'ratings-rating-shim'))
        if score_to_rating:
            score_field = self.fields.pop('score')
            score_field.source = None  # drf complains if we specify source.
            self.fields['rating'] = score_field

    def validate_version(self, version):
        if self.partial:
            raise serializers.ValidationError(
                ugettext(u'You can\'t change the version of the add-on '
                         u'reviewed once the review has been created.'))

        addon = self.context['view'].get_addon_object()
        if not addon:
            # BaseRatingSerializer.validate() should complain about that, not
            # this method.
            return None
        version_inst = version['version']
        if version_inst.addon_id != addon.pk or not version_inst.is_public():
            raise serializers.ValidationError(
                ugettext(u'This version of the add-on doesn\'t exist or '
                         u'isn\'t public.'))
        return version

    def validate(self, data):
        data = super(RatingSerializer, self).validate(data)
        if not self.partial:
            if data['addon'].authors.filter(pk=data['user'].pk).exists():
                raise serializers.ValidationError(
                    ugettext(u'You can\'t leave a review on your own add-on.'))

            rating_exists_on_this_version = Rating.objects.filter(
                addon=data['addon'], user=data['user'],
                version=data['version']['version']).using('default').exists()
            if rating_exists_on_this_version:
                raise serializers.ValidationError(
                    ugettext(u'You can\'t leave more than one review for the '
                             u'same version of an add-on.'))
        return data

    def create(self, validated_data):
        if 'version' in validated_data:
            # Flatten this because create can't handle nested serializers
            validated_data['version'] = (
                validated_data['version'].get('version'))
        return super(RatingSerializer, self).create(validated_data)


class RatingVoteSerializer(serializers.ModelSerializer):
    vote = serializers.IntegerField(source=None)
    rating = RatingSerializer(read_only=True)
    user = BaseUserSerializer(read_only=True)
    addon = RatingAddonSerializer(read_only=True)

    class Meta:
        model = RatingVote
        fields = ('vote', 'rating', 'user', 'addon')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = kwargs.get('context', {}).get('request')

    def validate_vote(self, vote):
        """
         ensure the value of the vote field in the database can either be 1 or 0.
        """
        votes = dict(RatingVote.VOTES)
        votes_str = [votes[vote]+'('+str(vote)+')' for vote in votes][1:]
        if vote not in votes:
            raise serializers.ValidationError(ugettext(
                'Invalid vote [%s] - must be one of [%s]' %
                (vote, ', '.join(votes_str))))
        return vote

    def validate(self, data):
        """
        ensure voting only applies on reviews with text.
        """
        data['rating'] = self.context['view'].rating_object
        if not data['rating'].body:
            raise serializers.ValidationError(ugettext(
                "This rating can't be voted because it has no review text."))
        return data

    def save(self, **kwargs):
        instance = super().save(**kwargs)
        instance.rating.update(editorreview=True)
        return instance


class RatingFlagSerializer(serializers.ModelSerializer):
    flag = serializers.CharField()
    note = serializers.CharField(allow_null=True, required=False)
    rating = RatingSerializer(read_only=True)
    user = BaseUserSerializer(read_only=True)

    class Meta:
        model = RatingFlag
        fields = ('flag', 'note', 'rating', 'user')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = kwargs.get('context', {}).get('request')

    def validate_flag(self, flag):
        flags = dict(RatingFlag.FLAGS)
        if flag not in flags:
            raise serializers.ValidationError(ugettext(
                'Invalid flag [%s] - must be one of [%s]' %
                (flag, ','.join(flags))))
        return flag

    def validate(self, data):
        data['rating'] = self.context['view'].rating_object
        data['user'] = self.request.user
        if not data['rating'].body:
            raise serializers.ValidationError(ugettext(
                "This rating can't be flagged because it has no review text."))

        if 'note' in data and data['note'].strip():
            data['flag'] = RatingFlag.OTHER
        elif data.get('flag') == RatingFlag.OTHER:
            raise serializers.ValidationError(
                {'note': ugettext(
                    'A short explanation must be provided when selecting '
                    '"Other" as a flag reason.')})
        return data

    def save(self, **kwargs):
        instance = super().save(**kwargs)
        instance.rating.update(editorreview=True)
        return instance
