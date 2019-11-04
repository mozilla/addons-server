from django.contrib import admin
from django.db.models import Prefetch
from django.forms.fields import ChoiceField
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html, format_html_join
from django.utils.translation import ugettext_lazy as _

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse

from .models import Block


class BlockAdminAddMixin():

    def get_urls(self):
        # Drop the existing add_view path so we can use our own
        urls = [url for url in super().get_urls()
                if url.name != 'blocklist_block_add']
        my_urls = [
            path(
                'add/',
                self.admin_site.admin_view(self.input_guids_view),
                name='blocklist_block_add'),
            path(
                'add_single/',
                self.admin_site.admin_view(self.add_single_view),
                name='blocklist_block_add_single'),
            path(
                'add_mutiple/',
                self.admin_site.admin_view(self.add_multiple_view),
                name='blocklist_block_add_multiple'),
        ]
        return my_urls + urls

    def input_guids_view(self, request, form_url='', extra_context=None):
        errors = []
        if request.method == 'POST':
            guids_data = request.POST.get('guids')
            guids = guids_data.split(',') if guids_data else []
            if len(guids) == 1:
                guid = guids[0]
                if not Addon.unfiltered.filter(guid=guid).exists():
                    # We might want to do something better than this eventually
                    # - e.g. go to the multi_view once implemented.
                    errors.append(
                        _('Addon with specified GUID does not exist'))
                else:
                    # If the guid already has a Block go to the change view
                    existing = Block.objects.filter(addon__guid=guid).first()
                    if existing:
                        return redirect(
                            'admin:blocklist_block_change',
                            existing.id)
                    else:
                        # Otherwise proceed to the single guid add view
                        return redirect(
                            reverse('admin:blocklist_block_add_single') +
                            f'?guid={guid}')
            elif len(guids) > 1:
                # If there's > 1 guid go to multi view.
                return redirect(
                    'admin:blocklist_block_add_multiple')

        context = {}
        context.update({
            'add': True,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, None),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': 'Block Add-ons',
            'save_as': False,
            'errors': errors,
        })
        return TemplateResponse(
            request, "blocklist/add_guids.html", context)

    def add_single_view(self, request, form_url='', extra_context=None):
        """This is just the default django add view."""
        return self.add_view(
            request, form_url=form_url, extra_context=extra_context)

    def add_multiple_view(self, request, **kwargs):
        raise NotImplementedError


@admin.register(Block)
class BlockAdmin(BlockAdminAddMixin, admin.ModelAdmin):
    list_display = (
        'guid',
        'min_version',
        'max_version',
        'updated_by',
        'modified')
    readonly_fields = (
        'addon_guid',
        'addon_name',
        'addon_updated',
        'users',
        'review_listed_link',
        'review_unlisted_link',
        'block_history',
        'url_link',
    )
    ordering = ['-modified']
    view_on_site = False
    list_select_related = ('updated_by',)
    actions = ['delete_selected']

    addon_instance = None

    class Media:
        css = {
            'all': ('css/admin/blocklist_block.css',)
        }

    def addon_guid(self, obj):
        return self.addon_instance.guid
    addon_guid.short_description = 'Add-on GUID'

    def addon_name(self, obj):
        return self.addon_instance.name

    def addon_updated(self, obj):
        return self.addon_instance.modified

    def users(self, obj):
        return self.addon_instance.average_daily_users

    def review_listed_link(self, obj):
        has_listed = any(
            True for v in self._get_addon_versions().values()
            if v == amo.RELEASE_CHANNEL_LISTED)
        if has_listed:
            url = reverse(
                'reviewers.review',
                kwargs={'addon_id': self.addon_instance.pk})
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Listed'))
        return ''

    def review_unlisted_link(self, obj):
        has_unlisted = any(
            True for v in self._get_addon_versions().values()
            if v == amo.RELEASE_CHANNEL_UNLISTED)
        if has_unlisted:
            url = reverse(
                'reviewers.review', args=('unlisted'),
                kwargs={'addon_id': self.addon_instance.pk})
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Unlisted'))
        return ''

    def url_link(self, obj):
        return format_html('<a href="{}">{}</a>', obj.url, obj.url)

    def block_history(self, obj):
        history_format_string = (
            '<li>{}. {} {} Versions {} - {}<ul><li>{}</li></ul></li>')

        logs = ActivityLog.objects.for_addons((obj.addon,)).order_by('created')
        log_entries_gen = (
            (log.created.date(),
             log.user.name,
             str(log),
             log.details['min_version'],
             log.details['max_version'],
             log.details['reason'])
            for log in logs)
        return format_html(
            '<ul>\n{}\n</ul>',
            format_html_join('\n', history_format_string, log_entries_gen))

    def get_fieldsets(self, request, obj):
        details = (
            None, {
                'fields': (
                    'addon_guid',
                    'addon_name',
                    'addon_updated',
                    'users',
                    ('review_listed_link', 'review_unlisted_link'))
            })
        history = (
            'Block History', {
                'fields': (
                    'block_history',
                )
            })
        edit = (
            'Add New Block' if not obj else 'Edit Block', {
                'fields': (
                    'min_version',
                    'max_version',
                    'url' if not obj else ('url', 'url_link'),
                    'reason',
                    'include_in_legacy'),
            })

        return (details, history, edit) if obj is not None else (details, edit)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        if not change:
            obj.addon = self.addon_instance
        action = (
            amo.LOG.BLOCKLIST_BLOCK_EDITED if change else
            amo.LOG.BLOCKLIST_BLOCK_ADDED)
        details = {
            'guid': obj.guid,
            'min_version': obj.min_version,
            'max_version': obj.max_version,
            'url': obj.url,
            'reason': obj.reason,
            'include_in_legacy': obj.include_in_legacy,
        }
        super().save_model(request, obj, form, change)
        ActivityLog.create(action, obj.addon, obj.guid, details=details)

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        ActivityLog.create(
            amo.LOG.BLOCKLIST_BLOCK_DELETED, obj.addon, obj.guid)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            Prefetch(
                'addon', queryset=Addon.unfiltered.all().only_translations()),
        )

    def _get_addon_versions(self):
        """Add some caching on the version queries.
        We add it to the addon_instance object rather than self because the
        ModelAdmin instance can be reused by subsequent requests.
        """
        if not hasattr(self.addon_instance, '_addon_versions_cache'):
            qs = self.addon_instance.versions(
                manager='unfiltered_for_relations').values(
                'version', 'channel')
            self.addon_instance._addon_versions_cache = {
                version['version']: version['channel'] for version in qs}
        return self.addon_instance._addon_versions_cache

    def get_form(self, request, obj=None, **kwargs):
        if obj:
            self.addon_instance = obj.addon
        else:
            self.addon_instance = Addon.unfiltered.filter(
                guid=request.GET.get('guid')).first()
        return super().get_form(request, obj=obj, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ('min_version', 'max_version'):
            kwargs['choices'] = (
                (version, version) for version in
                ([db_field.default] + list(self._get_addon_versions().keys())))
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)
