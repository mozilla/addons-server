from django.contrib import admin, messages
from django.core.urlresolvers import reverse
from django.db.utils import IntegrityError
from django.utils.html import format_html, format_html_join
from django.utils.translation import ugettext_lazy as _

from olympia.abuse.models import AbuseReport
from olympia.access.admin import GroupUserInline
from olympia.activity.models import ActivityLog, UserLog
from olympia.addons.models import Addon
from olympia.amo.utils import render
from olympia.bandwagon.models import Collection
from olympia.ratings.models import Rating

from . import forms
from .models import DeniedName, UserProfile


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('id', '^email', '^username')
    # A custom field used in search json in zadmin, not django.admin.
    search_fields_response = 'email'
    inlines = (GroupUserInline,)

    readonly_fields = ('id', 'picture_img', 'deleted', 'is_public',
                       'last_login', 'last_login_ip', 'known_ip_adresses',
                       'last_known_activity_time', 'ratings_created',
                       'collections_created', 'addons_created', 'activity',
                       'abuse_reports_by_this_user',
                       'abuse_reports_for_this_user')
    fieldsets = (
        (None, {
            'fields': ('id', 'email', 'username', 'display_name',
                       'biography', 'homepage', 'location', 'occupation',
                       'picture_img'),
        }),
        ('Flags', {
            'fields': ('display_collections', 'display_collections_fav',
                       'deleted', 'is_public'),
        }),
        ('Content', {
            'fields': ('addons_created', 'collections_created',
                       'ratings_created')
        }),
        ('Abuse Reports', {
            'fields': ('abuse_reports_by_this_user',
                       'abuse_reports_for_this_user')
        }),
        ('Admin', {
            'fields': ('last_login', 'last_known_activity_time', 'activity',
                       'last_login_ip', 'known_ip_adresses', 'notes', ),
        }),
    )

    def picture_img(self, obj):
        return format_html(u'<img src="{}" />', obj.picture_url)
    picture_img.short_description = _(u'Profile Photo')

    def known_ip_adresses(self, obj):
        ip_adresses = set(Rating.objects.filter(user=obj)
                                .values_list('ip_address', flat=True)
                                .order_by().distinct())
        ip_adresses.add(obj.last_login_ip)
        contents = format_html_join(
            '', "<li>{}</li>", ((ip,) for ip in ip_adresses))
        return format_html('<ul>{}</ul>', contents)

    def last_known_activity_time(self, obj):
        from django.contrib.admin.utils import display_for_value
        # We sort by -created by default, so first() gives us the last one, or
        # None.
        user_log = (
            UserLog.objects.filter(user=obj)
            .values_list('created', flat=True).first())
        return display_for_value(user_log, '')

    def related_content_link(self, obj, related_class, related_field,
                             related_manager='objects'):
        url = 'admin:{}_{}_changelist'.format(
            related_class._meta.app_label, related_class._meta.model_name)
        queryset = getattr(related_class, related_manager).filter(
            **{related_field: obj})
        return format_html(
            '<a href="{}?{}={}">{}</a>',
            reverse(url), related_field, obj.pk, queryset.count())

    def collections_created(self, obj):
        return self.related_content_link(obj, Collection, 'author')
    collections_created.short_description = _('Collections')

    def addons_created(self, obj):
        return self.related_content_link(obj, Addon, 'authors',
                                         related_manager='unfiltered')
    addons_created.short_description = _('Addons')

    def ratings_created(self, obj):
        return self.related_content_link(obj, Rating, 'user')
    ratings_created.short_description = _('Ratings')

    def activity(self, obj):
        return self.related_content_link(obj, ActivityLog, 'user')
    activity.short_description = _('Activity Logs')

    def abuse_reports_by_this_user(self, obj):
        return self.related_content_link(obj, AbuseReport, 'reporter')

    def abuse_reports_for_this_user(self, obj):
        return self.related_content_link(obj, AbuseReport, 'user')


class DeniedModelAdmin(admin.ModelAdmin):
    def add_view(self, request, form_url='', extra_context=None):
        """Override the default admin add view for bulk add."""
        form = self.model_add_form()
        if request.method == 'POST':
            form = self.model_add_form(request.POST)
            if form.is_valid():
                inserted = 0
                duplicates = 0

                for x in form.cleaned_data[self.add_form_field].splitlines():
                    # check with the cache
                    if self.deny_list_model.blocked(x):
                        duplicates += 1
                        continue
                    try:
                        self.deny_list_model.objects.create(
                            **{self.model_field: x.lower()})
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
        return render(request, self.template_path, {'form': form})


class DeniedNameAdmin(DeniedModelAdmin):
    list_display = search_fields = ('name',)
    deny_list_model = DeniedName
    model_field = 'name'
    model_add_form = forms.DeniedNameAddForm
    add_form_field = 'names'
    template_path = 'users/admin/denied_name/add.html'


admin.site.register(UserProfile, UserAdmin)
admin.site.register(DeniedName, DeniedNameAdmin)
