import functools
import ipaddress
import itertools

from django import http
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.db.models import (
    CharField,
    Count,
    FilteredRelation,
    Q,
)

from django.db.utils import IntegrityError
from django.http import (
    Http404,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.template.response import TemplateResponse
from django.urls import re_path, reverse
from django.utils.encoding import force_str
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext, gettext_lazy as _

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.activity.models import ActivityLog, IPLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.admin import CommaSearchInAdminMixin
from olympia.amo.fields import IPAddressBinaryField
from olympia.amo.models import GroupConcat
from olympia.api.models import APIKey, APIKeyConfirmation
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating
from olympia.zadmin.admin import related_content_link, related_single_content_link

from . import forms
from .models import (
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


@admin.register(UserProfile)
class UserAdmin(CommaSearchInAdminMixin, admin.ModelAdmin):
    list_display = ('__str__', 'email', 'last_login', 'is_public', 'deleted')
    search_fields = ('=id', '^email', '^username')
    # A custom ip address search is implemented in get_search_results() using
    # IPLog. It sets an annotation that we can then use in the
    # custom `known_ip_adresses` method referenced in the line below, which
    # is added to the list_display fields for IP searches.
    extra_list_display_for_ip_searches = ('known_ip_adresses',)
    # A custom field used in search json in zadmin, not django.admin.
    search_fields_response = 'email'
    inlines = (GroupUserInline,)
    show_full_result_count = False  # Turn off to avoid the query.

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
        'is_public',
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
                'fields': ('display_collections', 'deleted', 'is_public'),
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

    actions = ['ban_action', 'reset_api_key_action', 'reset_session_action']

    class Media:
        js = ('js/admin/userprofile.js',)
        css = {'all': ('css/admin/userprofile.css',)}

    def get_list_display(self, request):
        search_term = request.GET.get('q')
        if search_term and self.ip_addresses_if_query_is_all_ip_addresses(search_term):
            return (*self.list_display, *self.extra_list_display_for_ip_searches)
        return self.list_display

    def ip_addresses_if_query_is_all_ip_addresses(self, search_term):
        search_terms = search_term.split(',')
        ips = []
        for term in search_terms:
            try:
                ip = ipaddress.ip_address(term)
                ip_str = str(ip)
                if ip_str != term:
                    raise ValueError
                ips.append(ip_str)
            except ValueError:
                break
        if search_terms == ips:
            # If all we are searching for are IPs, we'll use our custom IP
            # search.
            # Note that this comparison relies on ips being stored as strings,
            # if that were to change that it would break.
            return ips
        return None

    def get_search_results(self, request, queryset, search_term):
        ips = self.ip_addresses_if_query_is_all_ip_addresses(search_term)
        if ips:
            condition = Q(activitylog__iplog__ip_address_binary__in=ips)
            # We want to duplicate the joins against activitylog + iplog so
            # that one is used for the search, and the other for the group
            # concat showing all IPs for activities of that user. Django
            # doesn't let us do that out of the box, but through
            # FilteredRelation we can force it...
            annotations = {
                'activity_ips': GroupConcat(
                    'activitylog__iplog__ip_address_binary',
                    distinct=True,
                    # You can't have multiple ip addresses in an IPv[4|6]Address object
                    # so we store the binary values in a CharField instead.
                    output_field=CharField(),
                ),
                'activitylog_filtered': FilteredRelation(
                    'activitylog__iplog', condition=condition
                ),
            }
            # ...and then add the most simple filter to "activate" the join
            # which has our search condition.
            queryset = queryset.annotate(**annotations).filter(
                activitylog_filtered__isnull=False
            )
            # A GROUP_BY will already have been applied thanks to our
            # annotations so we can let django know there won't be any
            # duplicates and avoid doing a DISTINCT.
            may_have_duplicates = False
        else:
            queryset, may_have_duplicates = super().get_search_results(
                request,
                queryset,
                search_term,
            )
        return queryset, may_have_duplicates

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
            # You need Users:Edit to be able to ban users and reset their api
            # key confirmation.
            actions.pop('ban_action')
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
            except UserProfile.DoesNotExist:
                raise http.Http404
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
        ActivityLog.create(amo.LOG.ADMIN_USER_ANONYMIZED, obj)
        obj.delete()

    def save_model(self, request, obj, form, change):
        changes = {
            k: (form.initial.get(k), form.cleaned_data.get(k))
            for k in form.changed_data
        }
        ActivityLog.create(amo.LOG.ADMIN_USER_EDITED, obj, details=changes)
        obj.save()

    def ban_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404()

        if not acl.action_allowed_for(request.user, amo.permissions.USERS_EDIT):
            return HttpResponseForbidden()

        ActivityLog.create(amo.LOG.ADMIN_USER_BANNED, obj)
        UserProfile.ban_and_disable_related_content_bulk([obj], move_files=True)
        kw = {'user': force_str(obj)}
        self.message_user(request, gettext('The user "%(user)s" has been banned.' % kw))
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

        ActivityLog.create(amo.LOG.ADMIN_USER_PICTURE_DELETED, obj)
        obj.delete_picture()
        kw = {'user': force_str(obj)}
        self.message_user(
            request,
            gettext('The picture belonging to user "%(user)s" has been deleted.' % kw),
        )
        return HttpResponseRedirect(
            reverse('admin:users_userprofile_change', args=(obj.pk,))
        )

    def ban_action(self, request, qs):
        users = []
        UserProfile.ban_and_disable_related_content_bulk(qs)
        for obj in qs:
            ActivityLog.create(amo.LOG.ADMIN_USER_BANNED, obj)
            users.append(force_str(obj))
        kw = {'users': ', '.join(users)}
        self.message_user(
            request, gettext('The users "%(users)s" have been banned.' % kw)
        )

    ban_action.short_description = _('Ban selected users')

    def reset_session_action(self, request, qs):
        users = []
        qs.update(auth_id=None)  # A new value will be generated at next login.
        for obj in qs:
            ActivityLog.create(amo.LOG.ADMIN_USER_SESSION_RESET, obj)
            users.append(force_str(obj))
        kw = {'users': ', '.join(users)}
        self.message_user(
            request, gettext('The users "%(users)s" had their session(s) reset.' % kw)
        )

    reset_session_action.short_description = _('Reset session')

    def reset_api_key_action(self, request, qs):
        users = []
        APIKeyConfirmation.objects.filter(user__in=qs).delete()
        APIKey.objects.filter(user__in=qs).update(is_active=None)
        for user in qs:
            ActivityLog.create(amo.LOG.ADMIN_API_KEY_RESET, user)
            users.append(force_str(user))
        kw = {'users': ', '.join(users)}
        self.message_user(
            request, gettext('The users "%(users)s" had their API Key reset.' % kw)
        )

    reset_api_key_action.short_description = _('Reset API Key')

    def picture_img(self, obj):
        return format_html('<img src="{}" />', obj.picture_url)

    picture_img.short_description = _('Profile Photo')

    def known_ip_adresses(self, obj):
        # activity_ips is an annotation added by get_search_results() above
        # thanks to a GROUP_CONCAT. If present, use that (avoiding making
        # extra queries for each row of results), otherwise, look everywhere
        # we can.
        activity_ips = getattr(obj, 'activity_ips', None)
        to_ipaddress = IPAddressBinaryField().to_python
        if activity_ips is not None:
            # The GroupConcat value is a comma seperated string of the binary values.
            ip_addresses = {to_ipaddress(ip) for ip in activity_ips.split(b',')}
        else:
            ip_addresses = set(
                Rating.objects.filter(user=obj)
                .values_list('ip_address', flat=True)
                .order_by()
                .distinct()
            )
            ip_addresses.update(
                itertools.chain(
                    *UserRestrictionHistory.objects.filter(user=obj)
                    .values_list('last_login_ip', 'ip_address')
                    .order_by()
                    .distinct()
                )
            )
            ip_addresses.add(obj.last_login_ip)
            # In the glorious future all these ip addresses will be IPv[4|6]Address
            # objects but for now some of them are strings so we have to convert.
            ip_addresses = {to_ipaddress(ip) for ip in ip_addresses if ip}
            ip_addresses.update(
                IPLog.objects.filter(activity_log__user=obj)
                .values_list('ip_address_binary', flat=True)
                .order_by()
                .distinct()
            )

        contents = format_html_join(
            '', '<li>{}</li>', ((ip,) for ip in sorted(ip_addresses))
        )
        return format_html('<ul>{}</ul>', contents)

    known_ip_adresses.short_description = 'Known IP addresses'

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
        return related_content_link(obj, Collection, 'author')

    collections_authorship.short_description = _('Collections')

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

    addons_authorship.short_description = _('Add-ons')

    def ratings_authorship(self, obj):
        return related_content_link(obj, Rating, 'user')

    ratings_authorship.short_description = _('Ratings')

    def activity(self, obj):
        return related_content_link(obj, ActivityLog, 'user')

    activity.short_description = _('Activity Logs')

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
class DeniedNameAdmin(admin.ModelAdmin):
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
class IPNetworkUserRestrictionAdmin(admin.ModelAdmin):
    list_display = ('network', 'restriction_type')
    list_filter = ('restriction_type',)
    search_fields = ('=network',)
    form = forms.IPNetworkUserRestrictionForm


@admin.register(EmailUserRestriction)
class EmailUserRestrictionAdmin(admin.ModelAdmin):
    list_display = ('email_pattern', 'restriction_type')
    list_filter = ('restriction_type',)
    search_fields = ('^email_pattern',)


@admin.register(DisposableEmailDomainRestriction)
class DisposableEmailDomainRestrictionAdmin(admin.ModelAdmin):
    list_display = ('domain', 'restriction_type')
    list_filter = ('restriction_type',)
    search_fields = ('^domain',)


@admin.register(UserRestrictionHistory)
class UserRestrictionHistoryAdmin(admin.ModelAdmin):
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

    user_link.short_description = _('User')

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        base_qs = UserRestrictionHistory.objects.all()
        return base_qs.prefetch_related('user')


@admin.register(UserHistory)
class UserHistoryAdmin(admin.ModelAdmin):
    view_on_site = False
    search_fields = ('=user__id', '^email')

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
