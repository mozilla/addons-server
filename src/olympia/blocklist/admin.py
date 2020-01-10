from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.forms import modelform_factory
from django.forms.fields import CharField, ChoiceField
from django.forms.widgets import HiddenInput
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html

from olympia.activity.models import ActivityLog
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseTemporaryRedirect

from .forms import MultiAddForm, MultiDeleteForm
from .models import Block, BlockSubmission
from .tasks import create_blocks_from_multi_block
from .utils import (
    block_activity_log_delete, block_activity_log_save, format_block_history)


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
                'delete_multiple/',
                self.admin_site.admin_view(self.delete_multiple_view),
                name='blocklist_block_delete_multiple'),
        ]
        return my_urls + urls

    def input_guids_view(self, request, form_url='', extra_context=None):
        if request.method == 'POST':
            form = MultiAddForm(request.POST)
            if form.is_valid():
                guids = form.data.get('guids', '').splitlines()
                if len(guids) == 1:
                    # If the guid already has a Block go to the change view
                    if form.existing_block:
                        return redirect(
                            'admin:blocklist_block_change',
                            form.existing_block.id)
                    else:
                        # Otherwise proceed to the single guid add view
                        return redirect(
                            reverse('admin:blocklist_block_add_single') +
                            f'?guid={guids[0]}')
                elif len(guids) > 1:
                    # If there's > 1 guid go to multi view.
                    return HttpResponseTemporaryRedirect(
                        reverse('admin:blocklist_blocksubmission_add'))
        else:
            form = MultiAddForm()
        return self._render_multi_guid_input(
            request, form, title='Block Add-ons')

    def delete_multiple_view(self, request, form_url='', extra_context=None):
        if request.method == 'POST':
            if request.POST.get('action') == 'delete_selected':
                # it's the confirmation so redirect to changelist to handle
                return HttpResponseTemporaryRedirect(
                    reverse('admin:blocklist_block_changelist'))
            form = MultiDeleteForm(request.POST)
            if form.is_valid():
                return admin.actions.delete_selected(
                    self, request, form.existing_block_qs)
        else:
            form = MultiDeleteForm()
        return self._render_multi_guid_input(
            request, form, title='Delete Blocks', add=False)

    def _render_multi_guid_input(self, request, form, title, add=True):
        context = {
            'form': form,
            'add': add,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, None),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': title,
            'save_as': False,
        }
        return TemplateResponse(
            request, 'blocklist/multi_guid_input.html', context)

    def add_single_view(self, request, form_url='', extra_context=None):
        """This is just the default django add view."""
        return self.add_view(
            request, form_url=form_url, extra_context=extra_context)


@admin.register(BlockSubmission)
class BlockSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'blocks_count',
        'all_blocks_saved',
        'updated_by',
        'modified',
    )
    fields = (
        'input_guids',
        'blocks_submitted',
        'min_version',
        'max_version',
        'url',
        'reason',
        'updated_by',
        'include_in_legacy',
    )
    readonly_fields = (
        'blocks_submitted',
        'updated_by',
    )
    ordering = ['-created']
    view_on_site = False
    list_select_related = ('updated_by', 'signoff_by')
    change_form_template = 'blocklist/block_submission_change_form.html'

    def has_delete_permission(self, request, obj=None):
        return False

    # Read-only mode
    def has_change_permission(self, request, obj=None):
        return False
    def get_readonly_fields(self, request, obj=None):
        ro_fields = super().get_readonly_fields(request, obj=obj)
        if obj:
            ro_fields += ('input_guids', 'min_version', 'max_version')
        return ro_fields

    def add_view(self, request, **kwargs):
        if not self.has_add_permission(request):
            raise PermissionDenied

        ModelForm = type(
            self.form.__name__, (self.form,), {
                'existing_min_version': CharField(widget=HiddenInput),
                'existing_max_version': CharField(widget=HiddenInput)})
        fields = [
            field for field in self.get_fields(request, obj=None)
            if field not in self.readonly_fields]
        MultiBlockForm = modelform_factory(
            self.model, fields=fields, form=ModelForm,
            widgets={'input_guids': HiddenInput()})

        guids_data = request.POST.get('guids', request.GET.get('guids'))
        if guids_data:
            # If we get a guids param it's a redirect from input_guids_view.
            form = MultiBlockForm(initial={
                'input_guids': guids_data,
                'existing_min_version': Block.MIN,
                'existing_max_version': Block.MAX})
        elif request.method == 'POST':
            # Otherwise, if its a POST try to process the form.
            form = MultiBlockForm(request.POST)
            frm_data = form.data
            # Check if the versions specified were the ones we calculated which
            # Blocks would be updated or skipped on.
            versions_unchanged = (
                frm_data['min_version'] == frm_data['existing_min_version'] and
                frm_data['max_version'] == frm_data['existing_max_version'])
            if form.is_valid() and versions_unchanged:
                # Save the object so we have the guids
                obj = form.save()
                obj.update(updated_by=request.user)
                self.log_addition(request, obj, [{'added': {}}])
                if obj.is_save_to_blocks_permitted:
                    # Then launch a task to async save the individual blocks
                    create_blocks_from_multi_block.delay(obj.id)
                if request.POST.get('_addanother'):
                    return redirect('admin:blocklist_block_add')
                else:
                    return redirect('admin:blocklist_block_changelist')
            else:
                guids_data = request.POST.get('input_guids')
                form_data = form.data.copy()
                form_data['existing_min_version'] = form_data['min_version']
                form_data['existing_max_version'] = form_data['max_version']
                form.data = form_data
        else:
            # if its not a POST and no ?guids there's nothing to do so go back
            return redirect('admin:blocklist_block_add')

        context = {
            'form': form,
            'add': True,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': 'Block Add-ons',
            'save_as': False,
        }
        load_full_objects = guids_data.count('\n') < GUID_FULL_LOAD_LIMIT
        objects = self.model.process_input_guids(
            guids_data,
            v_min=request.POST.get('min_version', Block.MIN),
            v_max=request.POST.get('max_version', Block.MAX),
            load_full_objects=load_full_objects)
        context.update(objects)
        if load_full_objects:
            Block.preload_addon_versions(objects['blocks'])
        return TemplateResponse(
            request, 'blocklist/block_submission_add_form.html', context)



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
    change_list_template = 'blocklist/block_change_list.html'

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
        choices = [
            (version, version) for version in (
                [default] + list(obj.addon_versions.keys())
            )
        ]
        value = getattr(obj, field)
        if value and (value, value) not in choices:
            choices = [(getattr(obj, field), '(invalid)')] + choices
        return choices

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
