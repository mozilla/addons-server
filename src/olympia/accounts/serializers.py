from django.conf import settings
from django.utils.translation import gettext

from rest_framework import serializers

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.access.models import Group
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import (
    ImageCheck,
    SafeStorage,
    clean_nl,
    has_links,
    subscribe_newsletter,
    unsubscribe_newsletter,
    urlparams,
)
from olympia.api.serializers import AMOModelSerializer, SiteStatusSerializer
from olympia.api.utils import is_gate_active
from olympia.api.validators import OneOrMorePrintableCharacterAPIValidator
from olympia.users import notifications
from olympia.users.models import DeniedName, UserProfile
from olympia.users.tasks import resize_photo


log = olympia.core.logger.getLogger('accounts')


class BaseUserSerializer(AMOModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ('id', 'name', 'url', 'username')

    def get_url(self, obj):
        def is_adminish(user):
            return user and acl.action_allowed_for(user, amo.permissions.USERS_EDIT)

        request = self.context.get('request', None)
        current_user = getattr(request, 'user', None) if request else None
        # Only return your own profile url, and for developers.
        if obj == current_user or is_adminish(current_user) or obj.is_public:
            return obj.get_absolute_url()

    # Used in subclasses.
    def get_permissions(self, obj):
        out = {perm for group in obj.groups_list for perm in group.rules.split(',')}
        return sorted(out)

    # Used in subclasses.
    def get_picture_url(self, obj):
        if obj.picture_type:
            return absolutify(obj.picture_url)
        return None


class PublicUserProfileSerializer(BaseUserSerializer):
    picture_url = serializers.SerializerMethodField()
    average_addon_rating = serializers.FloatField(
        source='averagerating', read_only=True
    )

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + (
            'average_addon_rating',
            'created',
            'biography',
            'has_anonymous_display_name',
            'has_anonymous_username',
            'homepage',
            'is_addon_developer',
            'is_artist',
            'location',
            'occupation',
            'num_addons_listed',
            'picture_type',
            'picture_url',
        )
        # This serializer should never be used for updates but just to be sure.
        read_only_fields = fields


class UserProfileSerializer(PublicUserProfileSerializer):
    display_name = serializers.CharField(
        min_length=2,
        max_length=50,
        validators=[OneOrMorePrintableCharacterAPIValidator()],
    )
    picture_upload = serializers.ImageField(use_url=True, write_only=True)
    permissions = serializers.SerializerMethodField()
    fxa_edit_email_url = serializers.SerializerMethodField()
    # Just Need to specify any field for the source - '*' is the entire obj.
    site_status = SiteStatusSerializer(source='*', read_only=True)

    class Meta(PublicUserProfileSerializer.Meta):
        fields = PublicUserProfileSerializer.Meta.fields + (
            'deleted',
            'display_name',
            'email',
            'fxa_edit_email_url',
            'last_login',
            'last_login_ip',
            'permissions',
            'picture_upload',
            'read_dev_agreement',
            'site_status',
            'username',
        )
        writeable_fields = (
            'biography',
            'display_name',
            'homepage',
            'location',
            'occupation',
            'picture_upload',
        )
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def get_fxa_edit_email_url(self, user):
        base_url = f'{settings.FXA_CONTENT_HOST}/settings'
        return urlparams(
            base_url, uid=user.fxa_id, email=user.email, entrypoint='addons'
        )

    def validate_biography(self, value):
        if has_links(clean_nl(str(value))):
            # There's some links, we don't want them.
            raise serializers.ValidationError(gettext('No links are allowed.'))
        return value

    def validate_display_name(self, value):
        if DeniedName.blocked(value):
            raise serializers.ValidationError(
                gettext('This display name cannot be used.')
            )
        return value

    def validate_homepage(self, value):
        if settings.DOMAIN.lower() in value.lower():
            raise serializers.ValidationError(
                gettext(
                    'The homepage field can only be used to link to '
                    'external websites.'
                )
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
            original = instance.picture_path_original

            storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
            with storage.open(original, 'wb') as original_file:
                for chunk in photo.chunks():
                    original_file.write(chunk)
            instance.update(picture_type=photo.content_type)
            resize_photo.delay(
                original,
                instance.picture_path,
                set_modified_on=instance.serializable_reference(),
            )
        return instance

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)

        if request and is_gate_active(request, 'del-accounts-fxa-edit-email-url'):
            data.pop('fxa_edit_email_url', None)
        return data


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
