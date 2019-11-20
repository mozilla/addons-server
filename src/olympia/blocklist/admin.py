from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.forms import modelform_factory
from django.forms.fields import ChoiceField
from django.forms.widgets import HiddenInput
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html, conditional_escape
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseTemporaryRedirect

from .models import Block, MultiBlockSubmit
from .tasks import create_blocks_from_multi_block
from .utils import block_activity_log_delete, block_activity_log_save


# The limit for how many GUIDs should be fully loaded with all metadata
GUID_FULL_LOAD_LIMIT = 100


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
            guids = guids_data.splitlines() if guids_data else []
            if len(guids) == 1:
                guid = guids[0]
                # If the guid already has a Block go to the change view
                existing = Block.objects.filter(guid=guid).first()
                if existing:
                    return redirect(
                        'admin:blocklist_block_change', existing.id)

                if not Addon.unfiltered.filter(guid=guid).exists():
                    # We might want to do something better than this eventually
                    # - e.g. go to the multi_view once implemented.
                    errors.append(
                        _('Addon with specified GUID does not exist'))
                else:
                    # Otherwise proceed to the single guid add view
                    return redirect(
                        reverse('admin:blocklist_block_add_single') +
                        f'?guid={guid}')
            elif len(guids) > 1:
                # If there's > 1 guid go to multi view.
                return HttpResponseTemporaryRedirect(
                    reverse('admin:blocklist_block_add_multiple'))

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
        if not self.has_add_permission(request):
            raise PermissionDenied
        guids_data = request.POST.get('guids', request.GET.get('guids'))
        context = {}
        fields = (
            'input_guids', 'min_version', 'max_version', 'url', 'reason',
            'include_in_legacy')
        MultiBlockForm = modelform_factory(
            MultiBlockSubmit, fields=fields,
            widgets={'input_guids': HiddenInput()})
        if guids_data:
            # If we get a guids param it's a redirect from input_guids_view.
            form = MultiBlockForm(initial={'input_guids': guids_data})
        elif request.method == 'POST':
            # Otherwise, if its a POST try to process the form.
            form = MultiBlockForm(request.POST)
            if form.is_valid():
                # Save the object so we have the guids
                obj = form.save()
                obj.update(updated_by=request.user)
                self.log_addition(request, obj, [{'added': {}}])
                # Then launch a task to async save the individual blocks
                create_blocks_from_multi_block.delay(obj.id)
                if request.POST.get('_addanother'):
                    return redirect('admin:blocklist_block_add')
                else:
                    return redirect('admin:blocklist_block_changelist')
            else:
                guids_data = request.POST.get('input_guids')
        else:
            # if its not a POST and no ?guids there's nothing to do so go back
            return redirect('admin:blocklist_block_add')
        context.update({
            'form': form,
            'add': True,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, None),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': 'Block Add-ons',
            'save_as': False,
        })
        load_full_objects = guids_data.count('\n') < GUID_FULL_LOAD_LIMIT
        objects = MultiBlockSubmit.process_input_guids(
            guids_data, load_full_objects=load_full_objects)
        context.update(objects)
        if load_full_objects:
            Block.preload_addon_versions(objects['new'])
        return TemplateResponse(
            request, 'blocklist/multiple_block.html', context)


def format_block_history(logs):
    def format_html_join_kw(sep, format_string, kwargs_generator):
        return mark_safe(conditional_escape(sep).join(
            format_html(format_string, **kwargs)
            for kwargs in kwargs_generator
        ))

    history_format_string = (
        '<li>'
        '{date}. {action} by {name}: {guid}{versions}. {legacy}'
        '<ul><li>{reason}</li></ul>'
        '</li>')
    guid_url_format_string = '<a href="{url}">{text}</a>'
    versions_format_string = ', versions {min} - {max}'

    log_entries_gen = (
        {'date': (
            format_html(
                guid_url_format_string,
                url=log.details.get('url'),
                text=log.created.date())
            if log.details.get('url') else log.created.date()),
         'action': amo.LOG_BY_ID[log.action].short,
         'name': log.author_name,
         'guid': log.details.get('guid'),
         'versions': (
            format_html(
                versions_format_string, **{
                    'min': log.details.get('min_version'),
                    'max': log.details.get('max_version')})
            if 'min_version' in log.details else ''),
         'legacy': (
            'Included in legacy blocklist.'
            if log.details.get('include_in_legacy') else ''),
         'reason': log.details.get('reason') or ''}
        for log in logs)
    return format_html(
        '<ul>\n{}\n</ul>',
        format_html_join_kw('\n', history_format_string, log_entries_gen))


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

    class Media:
        css = {
            'all': ('css/admin/blocklist_block.css',)
        }

    def addon_guid(self, obj):
        return obj.guid
    addon_guid.short_description = 'Add-on GUID'

    def addon_name(self, obj):
        return obj.addon.name

    def addon_updated(self, obj):
        return obj.addon.modified

    def users(self, obj):
        return obj.addon.average_daily_users

    def url_link(self, obj):
        return format_html('<a href="{}">{}</a>', obj.url, obj.url)

    def block_history(self, obj):
        return format_block_history(
            ActivityLog.objects.for_guidblock(obj.guid).filter(
                action__in=Block.ACTIVITY_IDS).order_by('created'))

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

        return (details, history, edit)

    def render_change_form(self, request, context, add=False, change=False,
                           form_url='', obj=None):
        if add:
            context['adminform'].form.instance.guid = self.get_request_guid(
                request)
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url,
            obj=obj)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        if not change:
            obj.guid = self.get_request_guid(request)
        super().save_model(request, obj, form, change)
        block_activity_log_save(obj, change)

    def delete_model(self, request, obj):
        block_activity_log_delete(obj, request.user)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            block_activity_log_delete(obj, request.user)
        super().delete_queryset(request, queryset)

    def _get_version_choices(self, obj, field):
        default = obj._meta.get_field(field).default
        return (
            (version, version) for version in (
                [default] + list(obj.addon_versions.keys())
            )
        )

    def get_request_guid(self, request):
        return request.GET.get('guid')

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        obj = Block(guid=self.get_request_guid(request)) if not obj else obj
        form.base_fields['min_version'].choices = self._get_version_choices(
            obj, 'min_version')
        form.base_fields['max_version'].choices = self._get_version_choices(
            obj, 'max_version')
        return form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ('min_version', 'max_version'):
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)
