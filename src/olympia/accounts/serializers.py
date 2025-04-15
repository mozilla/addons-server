from django.conf import settings
from django.utils.translation import gettext

from rest_framework import serializers

import olympia.core.logger
from olympia import amo
from olympia.access.models import Group
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import (
    ImageCheck,
    clean_nl,
    has_urls,
    subscribe_newsletter,
    unsubscribe_newsletter,
    urlparams,
)
from olympia.api.fields import HttpHttpsOnlyURLField
from olympia.api.serializers import AMOModelSerializer, SiteStatusSerializer
from olympia.api.utils import is_gate_active
from olympia.users import notifications
from olympia.users.models import DeniedName, UserProfile
from olympia.users.utils import upload_picture


log = olympia.core.logger.getLogger('accounts')


class BaseUserSerializer(AMOModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ('id', 'name', 'url', 'username')

    def get_url(self, obj) -> str | None:
        return obj.get_absolute_url()

    # Used in subclasses.
    def get_permissions(self, obj) -> list[str]:
        out = {perm for group in obj.groups_list for perm in group.rules.split(',')}
        return sorted(out)

    # Used in subclasses.
    def get_picture_url(self, obj):
        if obj.picture_type:
            return absolutify(obj.picture_url)
        return None


class UserProfileSerializer(BaseUserSerializer):
    """
    A combined serializer that replaces FullUserProfileSerializer,
    MinimalUserProfileSerializer, and SelfUserProfileSerializer.

    The serializer's behavior is controlled by the 'view_type' context parameter:
    - 'full': Standard profile view (default)
    - 'minimal': Returns minimal profile data
    - 'self': Returns full profile data with additional fields for the user themselves
    """

    picture_url = serializers.SerializerMethodField()
    average_addon_rating = serializers.FloatField(
        source='averagerating', read_only=True
    )
    # Custom fields only for the 'self' view type
    picture_upload = serializers.ImageField(
        use_url=True, write_only=True, required=False
    )
    permissions = serializers.SerializerMethodField()
    fxa_edit_email_url = serializers.SerializerMethodField()
    site_status = SiteStatusSerializer(source='*', read_only=True)
    # Override homepage to use our own URLField with custom validation for security
    homepage = HttpHttpsOnlyURLField(required=False, allow_blank=True)

    # Fields used by MinimalUserProfileSerializer
    nullable_fields = (
        'biography',
        'homepage',
        'location',
        'occupation',
        'picture_type',
        'picture_url',
    )

    class Meta(BaseUserSerializer.Meta):
        model = UserProfile
        fields = BaseUserSerializer.Meta.fields + (
            'average_addon_rating',
            'biography',
            'created',
            'deleted',
            'display_name',
            'email',
            'fxa_edit_email_url',
            'has_anonymous_display_name',
            'has_anonymous_username',
            'homepage',
            'is_addon_developer',
            'is_artist',
            'last_login',
            'last_login_ip',
            'location',
            'occupation',
            'num_addons_listed',
            'permissions',
            'picture_type',
            'picture_upload',
            'picture_url',
            'read_dev_agreement',
            'site_status',
        )
        self_writeable_fields = (
            'biography',
            'display_name',
            'homepage',
            'location',
            'occupation',
            'picture_upload',
        )
        # By default, everything is read-only
        read_only_fields = fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set fields based on view_type
        view_type = self.context.get('view_type', 'full')

        # If it's a self view, make certain fields writable
        if view_type == 'self':
            for field_name in self.Meta.self_writeable_fields:
                if field_name in self.fields:
                    self.fields[field_name].read_only = False

    def get_permissions(self, obj) -> list[str]:
        if self.context.get('view_type') == 'self':
            return super().get_permissions(obj)
        return []

    def get_fxa_edit_email_url(self, user):
        if self.context.get('view_type') != 'self':
            return None

        base_url = f'{settings.FXA_CONTENT_HOST}/settings'
        return urlparams(
            base_url, uid=user.fxa_id, email=user.email, entrypoint='addons'
        )

    def validate_biography(self, value):
        if has_urls(clean_nl(str(value))):
            # There's some links, we don't want them.
            raise serializers.ValidationError(gettext('No links are allowed.'))
        return value

    def validate_display_name(self, value):
        if DeniedName.blocked(value):
            raise serializers.ValidationError(
                gettext('This display name cannot be used.')
            )
        return value

    def validate_picture_upload(self, value):
        image_check = ImageCheck(value)

        if value.content_type not in amo.IMG_TYPES or not image_check.is_image():
            raise serializers.ValidationError(
                gettext('Images must be either PNG or JPG.')
            )

        if image_check.is_animated():
            raise serializers.ValidationError(gettext('Images cannot be animated.'))

        if value.size > settings.MAX_PHOTO_UPLOAD_SIZE:
            raise serializers.ValidationError(
                gettext(
                    'Please use images smaller than %dMB.'
                    % (settings.MAX_PHOTO_UPLOAD_SIZE / 1024 / 1024)
                )
            )
        return value

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)

        photo = validated_data.get('picture_upload')
        if photo:
            upload_picture(instance, photo)
        return instance

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)
        view_type = self.context.get('view_type', 'full')

        if view_type == 'minimal':
            # Handle MinimalUserProfileSerializer logic
            if request and is_gate_active(
                request, 'mimimal-profile-has-all-fields-shim'
            ):
                data.update({field: None for field in self.nullable_fields})
            else:
                data = {
                    field: value
                    for field, value in data.items()
                    if field in BaseUserSerializer.Meta.fields
                }
        elif view_type == 'self':
            # Handle SelfUserProfileSerializer logic
            if request and is_gate_active(request, 'del-accounts-fxa-edit-email-url'):
                data.pop('fxa_edit_email_url', None)

        return data


# Keep the old serializer classes for backwards compatibility
# They simply use the new combined serializer with the appropriate view_type
class FullUserProfileSerializer(UserProfileSerializer):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('context', {})
        kwargs['context']['view_type'] = 'full'
        super().__init__(*args, **kwargs)


class MinimalUserProfileSerializer(UserProfileSerializer):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('context', {})
        kwargs['context']['view_type'] = 'minimal'
        super().__init__(*args, **kwargs)


class SelfUserProfileSerializer(UserProfileSerializer):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('context', {})
        kwargs['context']['view_type'] = 'self'
        super().__init__(*args, **kwargs)


group_rules = {
    'reviewer': 'Addons:Review',
    'admin': '*:*',
}


class AccountSuperCreateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    fxa_id = serializers.CharField(required=False)
    group = serializers.ChoiceField(choices=list(group_rules.items()), required=False)

    def validate_email(self, email):
        if email and UserProfile.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                'Someone with this email already exists in the system'
            )
        return email

    def validate_username(self, username):
        if username and UserProfile.objects.filter(username=username).exists():
            raise serializers.ValidationError(
                'Someone with this username already exists in the system'
            )
        return username

    def validate_group(self, group):
        if group:
            rule = group_rules[group]
            # This isn't perfect. It makes an assumption that a single group
            # will exist having a *single* rule for what we want. In the
            # case of reviewers and admins this should always be true.
            qs = Group.objects.filter(rules=rule)
            count = qs.count()
            if count != 1:
                log.info(
                    'Super creation: looking for group with '
                    'permissions {} {} (count: {})'.format(group, rule, count)
                )
                raise serializers.ValidationError(
                    'Could not find a permissions group with the exact rules needed.'
                )
            group = qs.get()
        return group


class UserNotificationSerializer(serializers.Serializer):
    name = serializers.CharField(source='notification.short')
    enabled = serializers.BooleanField()
    mandatory = serializers.BooleanField(source='notification.mandatory')

    def update(self, instance, validated_data):
        if instance.notification.mandatory:
            raise serializers.ValidationError(
                "Attempting to set [%s] to %s. Mandatory notifications can't "
                'be modified'
                % (instance.notification.short, validated_data.get('enabled'))
            )

        enabled = validated_data['enabled']

        request = self.context['request']
        current_user = request.user

        remote_by_id = {ntfn.id: ntfn for ntfn in notifications.REMOTE_NOTIFICATIONS}

        if instance.notification_id in remote_by_id:
            notification = remote_by_id[instance.notification_id]
            if not enabled:
                unsubscribe_newsletter(current_user, notification.basket_newsletter_id)
            elif enabled:
                subscribe_newsletter(
                    current_user, notification.basket_newsletter_id, request=request
                )
        elif 'enabled' in validated_data:
            # Only save if non-mandatory and 'enabled' is set.
            # Ignore other fields.
            instance.enabled = validated_data['enabled']
            # Not .update because some of the instances are new.
            instance.save()
        return instance
