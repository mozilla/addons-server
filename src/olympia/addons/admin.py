from urllib.parse import urlencode, urljoin

from django import http, forms
from django.conf import settings
from django.contrib import admin
from django.core import validators
from django.forms.models import modelformset_factory
from django.urls import resolve
from django.utils.html import format_html
from django.utils.translation import ugettext, ugettext_lazy as _

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.urlresolvers import reverse
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.versions.models import Version
from olympia.zadmin.admin import related_content_link

from . import models
from .forms import AdminBaseFileFormSet, FileStatusForm


log = olympia.core.logger.getLogger('z.addons.admin')


class AddonUserInline(admin.TabularInline):
    model = AddonUser
    raw_id_fields = ('user',)
    readonly_fields = ('user_profile_link',)
    extra = 0

    def user_profile_link(self, obj):
        if obj.pk:
            return format_html(
                '<a href="{}">Admin User Profile</a> ({})',
                reverse('admin:users_userprofile_change', args=(obj.user.pk,)),
                obj.user.email)
        else:
            return ''
    user_profile_link.short_description = 'User Profile'


class FileInlineChecks(admin.checks.InlineModelAdminChecks):
    def _check_relation(self, obj, parent_model):
        """File doesn't have a direct FK to Addon (it's via Version) so we have
        to bypass this check.
        """
        return []


class FileInline(admin.TabularInline):
    model = File
    extra = 0
    max_num = 0
    fields = (
        'created', 'version__version', 'version__channel', 'platform',
        'status', 'hash_link')
    editable_fields = ('status',)
    readonly_fields = tuple(set(fields) - set(editable_fields))
    can_delete = False
    view_on_site = False
    template = 'admin/addons/file_inline.html'
    checks_class = FileInlineChecks

    def version__version(self, obj):
        return obj.version.version + (
            ' - Deleted' if obj.version.deleted else '')
    version__version.short_description = 'Version'

    def version__channel(self, obj):
        return obj.version.get_channel_display()
    version__channel.short_description = 'Channel'

    def hash_link(self, obj):
        url = reverse('zadmin.recalc_hash', args=(obj.id,))
        template = '<a href="{}" class="recalc" title="{}">Recalc Hash</a>'
        return format_html(template, url, obj.hash)
    hash_link.short_description = 'Hash'

    def get_formset(self, request, obj=None, **kwargs):
        self.instance = obj
        Formset = modelformset_factory(
            File,
            form=FileStatusForm,
            formset=AdminBaseFileFormSet,
            extra=self.get_extra(request, obj, **kwargs),
            min_num=self.get_min_num(request, obj, **kwargs),
            max_num=self.get_max_num(request, obj, **kwargs),
        )
        return Formset

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        self.pager = amo.utils.paginate(
            request,
            Version.unfiltered.filter(addon=self.instance).values_list(
                'pk', flat=True),
            30)
        # A list coercion so this doesn't result in a subquery with a LIMIT
        # which MySQL doesn't support (at this time).
        versions = list(self.pager.object_list)
        qs = super().get_queryset(request).filter(
            version__in=versions).order_by('-version__id')
        return qs.select_related('version')


class AddonAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/l10n.css', 'css/admin/pagination.css')
        }
        js = (
            'admin/js/jquery.init.js', 'js/admin/l10n.js',
            'js/admin/recalc_hash.js'
        )

    exclude = ('authors',)
    list_display = ('__str__', 'type', 'guid', 'status', 'average_rating',
                    'reviewer_links')
    list_filter = ('type', 'status')
    search_fields = ('id', '^guid', '^slug')
    inlines = (AddonUserInline, FileInline)
    readonly_fields = ('id', 'created', 'status_with_admin_manage_link',
                       'average_rating', 'bayesian_rating',
                       'total_ratings_link', 'text_ratings_count',
                       'weekly_downloads', 'total_downloads',
                       'average_daily_users')

    fieldsets = (
        (None, {
            'fields': ('id', 'created', 'name', 'slug', 'guid',
                       'default_locale', 'type',
                       'status', 'status_with_admin_manage_link'),
        }),
        ('Details', {
            'fields': ('summary', 'description', 'homepage', 'eula',
                       'privacy_policy', 'developer_comments', 'icon_type',
                       ),
        }),
        ('Support', {
            'fields': ('support_url', 'support_email'),
        }),
        ('Stats', {
            'fields': ('total_ratings_link', 'average_rating',
                       'bayesian_rating', 'text_ratings_count',
                       'weekly_downloads', 'total_downloads',
                       'average_daily_users'),
        }),
        ('Flags', {
            'fields': ('disabled_by_user', 'view_source', 'requires_payment',
                       'is_experimental', 'reputation'),
        }),
        ('Dictionaries and Language Packs', {
            'fields': ('target_locale',),
        }))

    def queryset(self, request):
        return models.Addon.unfiltered

    def total_ratings_link(self, obj):
        return related_content_link(
            obj, Rating, 'addon', related_manager='without_replies',
            count=obj.total_ratings)
    total_ratings_link.short_description = _(u'Ratings')

    def reviewer_links(self, obj):
        links = []
        if obj.has_listed_versions(include_deleted=True):
            links.append(
                '<a href="{}">{}</a>'.format(
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['listed', obj.id]),
                    ),
                    _(u'Reviewer Tools (listed)'),
                )
            )
        if obj.has_unlisted_versions(include_deleted=True):
            links.append(
                '<a href="{}">{}</a>'.format(
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['unlisted', obj.id]),
                    ),
                    _(u'Reviewer Tools (unlisted)'),
                )
            )
        return format_html('&nbsp;|&nbsp;'.join(links))

    reviewer_links.short_description = _(u'Reviewer links')

    def status_with_admin_manage_link(self, obj):
        # We don't want admins to be able to change the status without logging
        # that it happened. So, for now, instead of letting them change the
        # status in the django admin, display it as readonly and link to the
        # zadmin manage page, which does implement the logging part (and more).
        # https://github.com/mozilla/addons-server/issues/7268
        link = reverse('zadmin.addon_manage', args=(obj.slug,))
        return format_html(u'<a href="{}">{}</a>',
                           link, obj.get_status_display())

    def change_view(self, request, object_id, form_url='', extra_context=None):
        lookup_field = Addon.get_lookup_field(object_id)
        if lookup_field != 'pk':
            try:
                if lookup_field == 'slug':
                    addon = self.queryset(request).all().get(slug=object_id)
                elif lookup_field == 'guid':
                    addon = self.queryset(request).get(guid=object_id)
            except Addon.DoesNotExist:
                raise http.Http404
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.id and addon.id != object_id:
                url = request.path.replace(object_id, str(addon.id), 1)
                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)

        return super().change_view(request, object_id, form_url,
                                   extra_context=extra_context)

    def render_change_form(self, request, context, add=False, change=False,
                           form_url='', obj=None):
        context.update(
            {
                'external_site_url': settings.EXTERNAL_SITE_URL,
                'has_listed_versions': obj.has_listed_versions(
                    include_deleted=True
                ) if obj else False,
                'has_unlisted_versions': obj.has_unlisted_versions(
                    include_deleted=True
                ) if obj else False
            }
        )

        return super().render_change_form(request=request, context=context,
                                          add=add, change=change,
                                          form_url=form_url, obj=obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'status' in form.changed_data:
            ActivityLog.create(
                amo.LOG.CHANGE_STATUS, obj, form.cleaned_data['status'])
            log.info('Addon "%s" status changed to: %s' % (
                obj.slug, form.cleaned_data['status']))


class FrozenAddonAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)


class ReplacementAddonForm(forms.ModelForm):
    def clean_path(self):
        path = None
        try:
            path = self.data.get('path')
            site = settings.SITE_URL
            if models.ReplacementAddon.path_is_external(path):
                if path.startswith(site):
                    raise forms.ValidationError(
                        'Paths for [%s] should be relative, not full URLs '
                        'including the domain name' % site)
                validators.URLValidator()(path)
            else:
                path = ('/' if not path.startswith('/') else '') + path
                resolve(path)
        except forms.ValidationError as validation_error:
            # Re-raise the ValidationError about full paths for SITE_URL.
            raise validation_error
        except Exception:
            raise forms.ValidationError('Path [%s] is not valid' % path)
        return path


class ReplacementAddonAdmin(admin.ModelAdmin):
    list_display = ('guid', 'path', 'guid_slug', '_url')
    form = ReplacementAddonForm

    def _url(self, obj):
        guid_param = urlencode({'guid': obj.guid})
        return format_html(
            '<a href="{}">Test</a>',
            reverse('addons.find_replacement') + '?%s' % guid_param)

    def guid_slug(self, obj):
        try:
            slug = models.Addon.objects.get(guid=obj.guid).slug
        except models.Addon.DoesNotExist:
            slug = ugettext(u'- Add-on not on AMO -')
        return slug

    def has_module_permission(self, request):
        # If one can see the changelist, then they have access to the module.
        return self.has_change_permission(request)

    def has_change_permission(self, request, obj=None):
        # If an obj is passed, then we're looking at the individual change page
        # for a replacement addon, otherwise we're looking at the list. When
        # looking at the list, we also allow users with Addons:Edit - they
        # won't be able to make any changes but they can see the list.
        if obj is not None:
            return super(ReplacementAddonAdmin, self).has_change_permission(
                request, obj=obj)
        else:
            return (
                acl.action_allowed(request, amo.permissions.ADDONS_EDIT) or
                super(ReplacementAddonAdmin, self).has_change_permission(
                    request, obj=obj))


admin.site.register(models.DeniedGuid)
admin.site.register(models.Addon, AddonAdmin)
admin.site.register(models.FrozenAddon, FrozenAddonAdmin)
admin.site.register(models.ReplacementAddon, ReplacementAddonAdmin)
