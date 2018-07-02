from urllib import urlencode

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core import validators
from django.core.urlresolvers import resolve
from django.utils.html import format_html
from django.utils.translation import ugettext, ugettext_lazy as _

from olympia import amo
from olympia.access import acl
from olympia.amo.urlresolvers import reverse

from . import models


class AddonAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': ('css/admin/l10n.css',)
        }
        js = ('js/admin/l10n.js',)

    exclude = ('authors',)
    list_display = ('__unicode__', 'type', 'guid',
                    'status_with_admin_manage_link', 'average_rating')
    list_filter = ('type', 'status')
    search_fields = ('id', '^guid', '^slug')

    readonly_fields = ('id', 'status_with_admin_manage_link',)

    fieldsets = (
        (None, {
            'fields': ('id', 'name', 'slug', 'guid', 'default_locale', 'type',
                       'status_with_admin_manage_link'),
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
            'fields': ('average_rating', 'bayesian_rating', 'total_ratings',
                       'text_ratings_count',
                       'weekly_downloads', 'total_downloads',
                       'average_daily_users'),
        }),
        ('Flags', {
            'fields': ('disabled_by_user', 'view_source', 'requires_payment',
                       'public_stats', 'is_experimental',
                       'external_software', 'reputation'),
        }),
        ('Dictionaries', {
            'fields': ('target_locale', 'locale_disambiguation'),
        }))

    def queryset(self, request):
        return models.Addon.unfiltered

    def status_with_admin_manage_link(self, obj):
        # We don't want admins to be able to change the status without logging
        # that it happened. So, for now, instead of letting them change the
        # status in the django admin, display it as readonly and link to the
        # zadmin manage page, which does implement the logging part (and more).
        # https://github.com/mozilla/addons-server/issues/7268
        link = reverse('zadmin.addon_manage', args=(obj.slug,))
        return format_html(u'<a href="{}">{}</a>',
                           link, obj.get_status_display())
    status_with_admin_manage_link.short_description = _(u'Status')


class FeatureAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)
    list_filter = ('application', 'locale')
    list_display = ('addon', 'application', 'locale')


class FrozenAddonAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)


class CompatOverrideRangeInline(admin.TabularInline):
    model = models.CompatOverrideRange
    # Exclude type since firefox only supports blocking right now.
    exclude = ('type',)


class CompatOverrideAdminForm(forms.ModelForm):

    def clean(self):
        if '_confirm' in self.data:
            raise forms.ValidationError('Click "Save" to confirm changes.')
        return self.cleaned_data


class CompatOverrideAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon',)
    inlines = [CompatOverrideRangeInline]
    form = CompatOverrideAdminForm


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
admin.site.register(models.CompatOverride, CompatOverrideAdmin)
admin.site.register(models.ReplacementAddon, ReplacementAddonAdmin)
