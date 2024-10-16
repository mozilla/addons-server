import re
from collections import OrderedDict

from django.conf import settings
from django.utils.translation import gettext, ngettext

from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from olympia.accounts.serializers import BaseUserSerializer
from olympia.addons.serializers import SimpleAddonSerializer, SimpleVersionSerializer
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active
from olympia.api.validators import NoURLsValidator
from olympia.users.utils import RestrictionChecker
from olympia.versions.models import Version

from .models import DeniedRatingWord, Rating, RatingFlag


class RatingAddonSerializer(SimpleAddonSerializer):
    def get_attribute(self, obj):
        # Avoid database queries if possible by re-using the addon object from
        # the view if there is one.
        return self.context['view'].get_addon_object() or obj.addon


class BaseRatingSerializer(AMOModelSerializer):
    addon = RatingAddonSerializer(read_only=True)
    body = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        validators=[NoURLsValidator()],
    )
    is_deleted = serializers.BooleanField(read_only=True, source='deleted')
    is_developer_reply = serializers.SerializerMethodField()
    is_latest = serializers.BooleanField(read_only=True)
    previous_count = serializers.IntegerField(read_only=True)
    user = BaseUserSerializer(read_only=True)
    flags = serializers.SerializerMethodField()

    class Meta:
        model = Rating
        fields = (
            'id',
            'addon',
            'body',
            'created',
            'flags',
            'is_deleted',
            'is_developer_reply',
            'is_latest',
            'previous_count',
            'user',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = kwargs.get('context', {}).get('request')

    def get_is_developer_reply(self, obj):
        return obj.reply_to_id is not None

    def _create_rating_flag(self, flag, note):
        # We will save the RatingFlag after the instance is saved.
        self._rating_flag_to_save = None
        if self.instance:
            try:
                self._rating_flag_to_save = RatingFlag.objects.get(
                    rating=self.instance, user_id=settings.TASK_USER_ID
                )
            except RatingFlag.DoesNotExist:
                pass
        if not self._rating_flag_to_save:
            self._rating_flag_to_save = RatingFlag(
                rating=self.instance, user_id=settings.TASK_USER_ID
            )
        self._rating_flag_to_save.flag = flag
        self._rating_flag_to_save.note = note[:100]

    def validate_body(self, body):
        # Clean up body.
        if body and '<br>' in body:
            body = re.sub('<br>', '\n', body)
        if word_matches := DeniedRatingWord.blocked(body, moderation=False):
            # if we have a match, raise a validation error immediately
            raise serializers.ValidationError(
                ngettext(
                    'The review text cannot contain the word: "{0}"',
                    'The review text cannot contain any of the words: "{0}"',
                    len(word_matches),
                ).format('", "'.join(word_matches))
            )

        if word_matches := DeniedRatingWord.blocked(body, moderation=True):
            self._create_rating_flag(
                RatingFlag.AUTO_MATCH, f'Words matched: [{", ".join(word_matches)}]'
            )

        return body

    def validate(self, data):
        data = super().validate(data)
        request = self.context['request']
        # Get the user from the request, don't allow clients to pick one themselves.
        user = request.user
        ip_address = request.META.get('REMOTE_ADDR', '')

        # There are a few fields that need to be set at creation time and never
        # modified afterwards:
        if not self.partial:
            # Because we want to avoid extra queries, addon is a
            # SerializerMethodField, which means it needs to be validated
            # manually. Fortunately the view does most of the work for us.
            data['addon'] = self.context['view'].get_addon_object()
            if data['addon'] is None:
                raise serializers.ValidationError(
                    {'addon': gettext('This field is required.')}
                )

            data['user'] = user
            # Also include the user ip adress.
            data['ip_address'] = ip_address
        else:
            # When editing, you can't change the add-on.
            if self.context['request'].data.get('addon'):
                raise serializers.ValidationError(
                    {
                        'addon': gettext(
                            "You can't change the add-on of a review once"
                            ' it has been created.'
                        )
                    }
                )

        if (
            not hasattr(self, '_rating_flag_to_save')
            and RestrictionChecker(request=request).should_moderate_rating()
        ):
            self._create_rating_flag(
                RatingFlag.AUTO_RESTRICTION,
                f'{user.email} or {{{ip_address}}} matched a UserRestriction',
            )

        if hasattr(self, '_rating_flag_to_save'):
            # If we have the _rating_flag_to_save set, we should be set the
            # flag and editorreview attributes on the instance we're about to
            # save.
            data['flag'] = True
            data['editorreview'] = True

        return data

    def get_flags(self, obj):
        if self.context['view'].should_include_flags():
            # should be maximum one RatingFlag per rating+user anyway.
            rating_flags = obj.ratingflag_set.filter(user=self.context['request'].user)
            return [
                {'flag': flag.flag, 'note': flag.note or None} for flag in rating_flags
            ]
        return None

    def to_representation(self, instance):
        out = super().to_representation(instance)
        if self.request and is_gate_active(self.request, 'ratings-title-shim'):
            out['title'] = None
        if not self.context['view'].should_include_flags():
            out.pop('flags', None)
        return out

    def save(self, **kwargs):
        instance = super().save(**kwargs)
        if hasattr(self, '_rating_flag_to_save'):
            self._rating_flag_to_save.rating = instance  # might be a new Rating
            self._rating_flag_to_save.save()
        return instance


class RatingSerializerReply(BaseRatingSerializer):
    """Serializer used for replies only."""

    body = serializers.CharField(
        allow_null=False,
        required=True,
        allow_blank=False,
    )

    def to_representation(self, obj):
        should_access_deleted = getattr(
            self.context['view'], 'should_access_deleted_ratings', False
        )
        if obj.deleted and not should_access_deleted:
            return None
        return super().to_representation(obj)

    def validate(self, data):
        # rating_object is set on the view by the reply() method.
        data['reply_to'] = self.context['view'].rating_object

        if data['reply_to'].reply_to:
            # Only one level of replying is allowed, so if it's already a
            # reply, we shouldn't allow that.
            msg = gettext("You can't reply to a review that is already a reply.")
            raise serializers.ValidationError(msg)

        data = super().validate(data)
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
        fields = BaseRatingSerializer.Meta.fields + ('score', 'reply', 'version')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        score_to_rating = self.request and is_gate_active(
            self.request, 'ratings-rating-shim'
        )
        if score_to_rating:
            score_field = self.fields.pop('score')
            score_field.source = None  # drf complains if we specify source.
            self.fields['rating'] = score_field

    def validate_version(self, version):
        if self.partial:
            raise serializers.ValidationError(
                gettext(
                    "You can't change the version of the add-on "
                    'reviewed once the review has been created.'
                )
            )

        addon = self.context['view'].get_addon_object()
        if not addon:
            # BaseRatingSerializer.validate() should complain about that, not
            # this method.
            return None
        version_inst = version['version']
        if version_inst.addon_id != addon.pk or not version_inst.is_public():
            raise serializers.ValidationError(
                gettext("This version of the add-on doesn't exist or isn't public.")
            )
        return version

    def validate(self, data):
        data = super().validate(data)
        if not self.partial:
            if data['addon'].authors.filter(pk=data['user'].pk).exists():
                raise serializers.ValidationError(
                    gettext("You can't leave a review on your own add-on.")
                )

            rating_exists_on_this_version = (
                Rating.objects.filter(
                    addon=data['addon'],
                    user=data['user'],
                    version=data['version']['version'],
                )
                .using('default')
                .exists()
            )
            if rating_exists_on_this_version:
                raise serializers.ValidationError(
                    gettext(
                        "You can't leave more than one review for the "
                        'same version of an add-on.'
                    )
                )
        return data

    def create(self, validated_data):
        if 'version' in validated_data:
            # Flatten this because create can't handle nested serializers
            validated_data['version'] = validated_data['version'].get('version')
        return super().create(validated_data)


class RatingFlagSerializer(AMOModelSerializer):
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
        flags = dict(RatingFlag.USER_FLAGS)
        if flag not in flags:
            raise serializers.ValidationError(
                gettext(
                    'Invalid flag [{}] - must be one of [{}]'.format(
                        flag, ','.join(flags)
                    )
                )
            )
        return flag

    def validate(self, data):
        data['rating'] = self.context['view'].rating_object
        data['user'] = self.request.user
        if not data['rating'].body:
            raise serializers.ValidationError(
                gettext("This rating can't be flagged because it has no review text.")
            )

        if 'note' in data and data['note'].strip():
            data['flag'] = RatingFlag.OTHER
        elif data.get('flag') == RatingFlag.OTHER:
            raise serializers.ValidationError(
                {
                    'note': gettext(
                        'A short explanation must be provided when selecting '
                        '"Other" as a flag reason.'
                    )
                }
            )
        return data

    def save(self, **kwargs):
        instance = super().save(**kwargs)
        instance.rating.update(editorreview=True, _signal=False)
        return instance
