import functools

from django import http
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.db import models
from django.db.models import Count, Q
from django.db.utils import IntegrityError
from django.forms import TextInput
from django.http import (
    Http404,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.template.response import TemplateResponse
from django.urls import re_path, reverse
from django.utils.encoding import force_str
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.admin import AMOModelAdmin
from olympia.amo.utils import backup_storage_enabled, create_signed_url_for_file_backup
from olympia.api.models import APIKey, APIKeyConfirmation
from olympia.bandwagon.models import Collection
from olympia.constants.activity import LOG_STORE_IPS
from olympia.ratings.models import Rating
from olympia.zadmin.admin import related_content_link, related_single_content_link

from . import forms
from .models import (
    BannedUserContent,
    DeniedName,
    DisposableEmailDomainRestriction,
    EmailUserRestriction,
    GroupUser,
    IPNetworkUserRestriction,
    UserHistory,
    UserProfile,
    UserRestrictionHistory,
)


class GroupUserInline(admin.TabularInline):
    model = GroupUser
    raw_id_fields = ('user',)
    extra = 0


class BannedUserContentInline(admin.TabularInline):
    verbose_name = 'Content disabled/deleted on user ban'
    model = BannedUserContent
    view_on_site = False
    fields = (
        'collections_link',
        'addons_link',
        'addons_users_link',
        'ratings_link',
        'picture_link',
    )
    readonly_fields = (
        'collections_link',
        'addons_link',
        'addons_users_link',
        'ratings_link',
        'picture_link',
    )
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj):
        # Instances of this model shouldn't be added through the admin.
        # The combination of this and extra = 0 means Django won't try to
        # pre-populate empty instances, which in turns avoids useless queries
        # that would be caused by banned_content_link().
        return False

    def banned_content_link(self, obj, related_class):
        return related_content_link(
            obj, related_class, 'bannedusercontent', related_manager='unfiltered'
        )

    def collections_link(self, obj):
        return self.banned_content_link(obj, Collection)

    def addons_link(self, obj):
        return self.banned_content_link(obj, Addon)

    def addons_users_link(self, obj):
        return self.banned_content_link(obj, AddonUser)

    def ratings_link(self, obj):
        return self.banned_content_link(obj, Rating)

    def picture_link(self, obj):
        if obj.picture_backup_name and backup_storage_enabled():
            url = create_signed_url_for_file_backup(obj.picture_backup_name)
            return mark_safe(f'<a href="{url}">{obj.picture_backup_name}</a>')
        return ''


@admin.register(UserProfile)
class UserAdmin(AMOModelAdmin):
    list_display = ('__str__', 'email', 'last_login', 'has_full_profile', 'deleted')
    # pk and IP address search are supported without needing to specify them in
    # search_fields (see `AMOModelAdmin`)
    search_fields = ('email__like',)
    # We can trigger search by ids with only one search term, if somehow an
    # admin wants to search for an email using a single query term that's all
    # numeric they can add a wildcard.
    minimum_search_terms_to_search_by_id = 1
    # A custom field used in search json in zadmin, not django.admin.
    search_fields_response = 'email'
    inlines = (GroupUserInline, BannedUserContentInline)
    search_by_ip_actions = LOG_STORE_IPS

    readonly_fields = (
        'abuse_reports_by_this_user',
        'abuse_reports_for_this_user',
        'activity',
        'addons_authorship',
        'banned',
        'collections_authorship',
        'created',
        'deleted',
        'has_active_api_key',
        'history_for_this_user',
        'id',
        'has_full_profile',
        'known_ip_adresses',
        'last_known_activity_time',
        'last_login',
        'last_login_ip',
        'modified',
        'picture_img',
        'ratings_authorship',
        'restriction_history_for_this_user',
    )
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'id',
                    'created',
                    'modified',
                    'email',
                    'history_for_this_user',
                    'fxa_id',
                    'username',
                    'display_name',
                    'biography',
                    'homepage',
                    'location',
                    'occupation',
                    'picture_img',
                ),
            },
        ),
        (
            'Flags',
            {
                'fields': ('deleted', 'has_full_profile'),
            },
        ),
        (
            'Content',
            {
                'fields': (
                    'addons_authorship',
                    'collections_authorship',
                    'ratings_authorship',
                )
            },
        ),
        (
            'Abuse Reports',
            {'fields': ('abuse_reports_by_this_user', 'abuse_reports_for_this_user')},
        ),
        (
            'Admin',
            {
                'fields': (
                    'last_login',
                    'last_known_activity_time',
                    'activity',
                    'restriction_history_for_this_user',
                    'last_login_ip',
                    'known_ip_adresses',
                    'banned',
                    'notes',
                    'bypass_upload_restrictions',
                    'has_active_api_key',
                )
            },
        ),
    )

    actions = [
        'ban_action',
        'unban_action',
        'reset_api_key_action',
        'reset_session_action',
    ]

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return functools.update_wrapper(wrapper, view)

        urlpatterns = super().get_urls()
        custom_urlpatterns = [
            re_path(
                r'^(?P<object_id>.+)/ban/$',
                wrap(self.ban_view),
                name='users_userprofile_ban',
            ),
            re_path(
                r'^(?P<object_id>.+)/unban/$',
                wrap(self.unban_view),
                name='users_userprofile_unban',
            ),
            re_path(
                r'^(?P<object_id>.+)/reset_api_key/$',
                wrap(self.reset_api_key_view),
                name='users_userprofile_reset_api_key',
            ),
            re_path(
                r'^(?P<object_id>.+)/reset_session/$',
                wrap(self.reset_session_view),
                name='users_userprofile_reset_session',
            ),
            re_path(
                r'^(?P<object_id>.+)/delete_picture/$',
                wrap(self.delete_picture_view),
                name='users_userprofile_delete_picture',
            ),
        ]
        return custom_urlpatterns + urlpatterns

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            # You need Users:Edit to be able to (un)ban users and reset their
            # api key confirmation/session.
            actions.pop('ban_action')
            actions.pop('unban_action')
            actions.pop('reset_api_key_action')
            actions.pop('reset_session_action')
        return actions

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['has_users_edit_permission'] = acl.action_allowed_for(
            request.user, amo.permissions.USERS_EDIT
        )

        lookup_field = UserProfile.get_lookup_field(object_id)
        if lookup_field != 'pk':
            try:
                if lookup_field == 'email':
                    user = UserProfile.objects.get(email=object_id)
            except UserProfile.DoesNotExist as exc:
                raise http.Http404 from exc
            url = request.path.replace(object_id, str(user.id), 1)
            if request.GET:
                url += '?' + request.GET.urlencode()
            return http.HttpResponsePermanentRedirect(url)

        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def delete_model(self, request, obj):
        # Deleting a user through the admin also deletes related content
        # produced by that user.
        ActivityLog.objects.create(amo.LOG.ADMIN_USER_ANONYMIZED, obj)
        obj.delete()

    def save_model(self, request, obj, form, change):
        changes = {
            k: (form.initial.get(k), form.cleaned_data.get(k))
            for k in form.changed_data
        }
        ActivityLog.objects.create(amo.LOG.ADMIN_USER_EDITED, obj, details=changes)
        obj.save()

    def ban_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        self.model.objects.filter(pk=obj.pk).ban_and_disable_related_content()
        kw = {'user': force_str(obj)}
        self.message_user(request, 'The user "%(user)s" has been banned.' % kw)
        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def unban_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        self.model.objects.filter(pk=obj.pk).unban_and_reenable_related_content()
        kw = {'user': force_str(obj)}
        self.message_user(request, 'The user "%(user)s" has been unbanned.' % kw)
        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def reset_api_key_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        self.reset_api_key_action(request, UserProfile.objects.filter(pk=obj.pk))

        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def reset_session_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        self.reset_session_action(request, UserProfile.objects.filter(pk=obj.pk))

        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def delete_picture_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        ActivityLog.objects.create(amo.LOG.ADMIN_USER_PICTURE_DELETED, obj)
        obj.delete_picture()
        kw = {'user': force_str(obj)}
        self.message_user(
            request,
            'The picture belonging to user "%(user)s" has been deleted.' % kw,
        )
        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def ban_action(self, request, qs):
        qs.ban_and_disable_related_content()
        kw = {'users': ', '.join(str(user) for user in qs)}
        self.message_user(request, 'The users "%(users)s" have been banned.' % kw)

    ban_action.short_description = 'Ban selected users'

    def unban_action(self, request, qs):
        qs.unban_and_reenable_related_content()
        kw = {'users': ', '.join(str(user) for user in qs)}
        self.message_user(request, 'The users "%(users)s" have been unbanned.' % kw)

    unban_action.short_description = 'Unban selected users'

    def reset_session_action(self, request, qs):
        users = []
        qs.update(auth_id=None)  # A new value will be generated at next login.
        for obj in qs:
            ActivityLog.objects.create(amo.LOG.ADMIN_USER_SESSION_RESET, obj)
            users.append(force_str(obj))
        kw = {'users': ', '.join(users)}
        self.message_user(
            request, 'The users "%(users)s" had their session(s) reset.' % kw
        )

    reset_session_action.short_description = 'Reset session'

    def reset_api_key_action(self, request, qs):
        users = []
        APIKeyConfirmation.objects.filter(user__in=qs).delete()
        APIKey.objects.filter(user__in=qs).update(is_active=None)
        for user in qs:
            ActivityLog.objects.create(amo.LOG.ADMIN_API_KEY_RESET, user)
            users.append(force_str(user))
        kw = {'users': ', '.join(users)}
        self.message_user(
            request, 'The users "%(users)s" had their API Key reset.' % kw
        )

    reset_api_key_action.short_description = 'Reset API Key'

    def picture_img(self, obj):
        return format_html('<img src="{}" />', obj.picture_url)

    picture_img.short_description = 'Profile Photo'

    def last_known_activity_time(self, obj):
        from django.contrib.admin.utils import display_for_value

        # We sort by -created by default, so first() gives us the last one, or
        # None.
        user_log = (
            ActivityLog.objects.filter(user=obj)
            .values_list('created', flat=True)
            .first()
        )
        return display_for_value(user_log, '')

    def has_active_api_key(self, obj):
        return obj.api_keys.filter(is_active=True).exists()

    has_active_api_key.boolean = True

    def collections_authorship(self, obj):
        return related_content_link(
            obj, Collection, 'author', related_manager='unfiltered'
        )

    collections_authorship.short_description = 'Collections'

    def addons_authorship(self, obj):
        counts = (
            AddonUser.unfiltered.filter(user=obj)
            .order_by()
            .aggregate(
                active_role=Count('role', filter=~Q(role=amo.AUTHOR_ROLE_DELETED)),
                deleted_role=Count('role', filter=Q(role=amo.AUTHOR_ROLE_DELETED)),
            )
        )
        return related_content_link(
            obj,
            Addon,
            'authors',
            text=format_html(
                '{} (active role), {} (deleted role)',
                counts['active_role'],
                counts['deleted_role'],
            ),
        )

    addons_authorship.short_description = 'Add-ons'

    def ratings_authorship(self, obj):
        return related_content_link(obj, Rating, 'user', related_manager='unfiltered')

    ratings_authorship.short_description = 'Ratings'

    def activity(self, obj):
        return related_content_link(obj, ActivityLog, 'user')

    activity.short_description = 'Activity Logs'

    def abuse_reports_by_this_user(self, obj):
        return related_content_link(obj, AbuseReport, 'reporter')

    def abuse_reports_for_this_user(self, obj):
        return related_content_link(obj, AbuseReport, 'user')

    def restriction_history_for_this_user(self, obj):
        return related_content_link(obj, UserRestrictionHistory, 'user')

    def history_for_this_user(self, obj):
        return related_content_link(obj, UserHistory, 'user')

    history_for_this_user.short_description = 'User History'


@admin.register(DeniedName)
class DeniedNameAdmin(AMOModelAdmin):
    list_display = search_fields = ('name',)
    view_on_site = False
    model = DeniedName
    model_add_form = forms.DeniedNameAddForm

    class Media:
        js = ('js/i18n/en-US.js',)

    def add_view(self, request, form_url='', extra_context=None):
        """Override the default admin add view for bulk add."""
        form = self.model_add_form()
        if request.method == 'POST':
            form = self.model_add_form(request.POST)
            if form.is_valid():
                inserted = 0
                duplicates = 0

                for x in form.cleaned_data['names'].splitlines():
                    # check with the cache
                    if self.model.blocked(x):
                        duplicates += 1
                        continue
                    try:
                        self.model.objects.create(**{'name': x.lower()})
                        inserted += 1
                    except IntegrityError:
                        # although unlikely, someone else could have added
                        # the same value.
                        # note: unless we manage the transactions manually,
                        # we do lose a primary id here.
                        duplicates += 1
                msg = '%s new values added to the deny list.' % (inserted)
                if duplicates:
                    msg += ' %s duplicates were ignored.' % (duplicates)
                messages.success(request, msg)
                form = self.model_add_form()
        context = {
            'form': form,
            'add': True,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'app_label': 'DeniedName',
            'opts': self.model._meta,
            'title': 'Add DeniedName',
            'save_as': False,
        }
        return TemplateResponse(
            request, 'admin/users/denied_name/add_form.html', context
        )


@admin.register(IPNetworkUserRestriction)
class IPNetworkUserRestrictionAdmin(AMOModelAdmin):
    list_display = ('network', 'restriction_type', 'reason')
    list_filter = ('restriction_type',)
    search_fields = ('=network',)
    form = forms.IPNetworkUserRestrictionForm
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'size': '125'})},
    }


@admin.register(EmailUserRestriction)
class EmailUserRestrictionAdmin(AMOModelAdmin):
    list_display = ('email_pattern', 'restriction_type', 'reason')
    list_filter = ('restriction_type',)
    search_fields = ('^email_pattern',)
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'size': '125'})},
    }


@admin.register(DisposableEmailDomainRestriction)
class DisposableEmailDomainRestrictionAdmin(AMOModelAdmin):
    list_display = ('domain', 'restriction_type', 'reason')
    list_filter = ('restriction_type',)
    search_fields = ('^domain',)
    formfield_overrides = {
        models.CharField: {'widget': TextInput(attrs={'size': '125'})},
    }


@admin.register(UserRestrictionHistory)
class UserRestrictionHistoryAdmin(AMOModelAdmin):
    raw_id_fields = ('user',)
    readonly_fields = (
        'restriction',
        'ip_address',
        'user_link',
        'last_login_ip',
        'created',
    )
    list_display = (
        'created',
        'user_link',
        'restriction',
        'ip_address',
        'last_login_ip',
    )
    extra = 0
    can_delete = False
    view_on_site = False

    def user_link(self, obj):
        return related_single_content_link(obj, 'user')

    user_link.short_description = 'User'

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        base_qs = UserRestrictionHistory.objects.all()
        return base_qs.prefetch_related('user')


@admin.register(UserHistory)
class UserHistoryAdmin(AMOModelAdmin):
    view_on_site = False
    search_fields = ('user__id', 'email__startswith')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
