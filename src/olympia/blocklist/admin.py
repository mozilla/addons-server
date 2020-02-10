from django.contrib import admin, auth, contenttypes
from django.core.exceptions import PermissionDenied
from django.forms.fields import CharField, ChoiceField
from django.forms.widgets import HiddenInput
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html

from olympia.activity.models import ActivityLog
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import HttpResponseTemporaryRedirect

from .forms import MultiAddForm, MultiDeleteForm
from .models import Block, BlockSubmission
from .tasks import create_blocks_from_multi_block
from .utils import block_activity_log_delete, format_block_history, splitlines


# The limit for how many GUIDs should be fully loaded with all metadata
GUID_FULL_LOAD_LIMIT = 100


def _get_version_choices(block, field_name):
    # field_name will be `min_version` or `max_version`
    default = block._meta.get_field(field_name).default
    choices = [
        (version, version) for version in (
            [default] + list(block.addon_versions.keys())
        )
    ]
    block_version = getattr(block, field_name)
    if block_version and (block_version, block_version) not in choices:
        # if the current version isn't in choices it's not a valid version of
        # the addon.  This is either because:
        # - the Block was created as a multiple submission so was a free input
        # - it's a new Block and the min|max_version was passed as a GET param
        # - the version was hard-deleted from the addon afterwards (unlikely)
        choices = [(block_version, '(invalid)')] + choices
    return choices


class BlockAdminAddMixin():

    def get_urls(self):
        my_urls = [
            path(
                'delete_multiple/',
                self.admin_site.admin_view(self.delete_multiple_view),
                name='blocklist_block_delete_multiple'),
        ]
        return my_urls + super().get_urls()

    def add_view(self, request, form_url='', extra_context=None):
        if request.method == 'POST':
            form = MultiAddForm(request.POST)
            if form.is_valid():
                guids = splitlines(form.data.get('guids'))
                if len(guids) == 1 and form.existing_block:
                    # If the guid already has a Block go to the change view
                    return redirect(
                        'admin:blocklist_block_change',
                        form.existing_block.id)
                elif len(guids) > 0:
                    # Otherwise go to multi view.
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


@admin.register(BlockSubmission)
class BlockSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'blocks_count',
        'signoff_state',
        'updated_by',
        'modified',
    )
    ordering = ['-created']
    view_on_site = False
    list_select_related = ('updated_by', 'signoff_by')
    change_form_template = 'blocklist/block_submission_change_form.html'

    class Media:
        css = {
            'all': ('css/admin/blocklist_blocksubmission.css',)
        }

    def has_delete_permission(self, request, obj=None):
        # For now, keep all BlockSubmission records.
        # TODO: define under what cirumstances records can be safely deleted.
        return False

    def is_pending_signoff(self, obj):
        return obj and obj.signoff_state == BlockSubmission.SIGNOFF_PENDING

    def has_change_permission(self, request, obj=None, strict=False):
        """ While a block submission is pending we want it to be partially
        editable (the url and reason).  Once it's been rejected or approved it
        can't be changed though.  Normally, as sign-off uses the changeform,
        we need to return true if the user has sign-off permission instead.
        We can override that permissive behavior with `strict=True`."""
        change_perm = super().has_change_permission(request, obj=obj)
        signoff_perm = (
            self.has_signoff_permission(request, obj=obj) and not strict)
        either_perm = change_perm or signoff_perm
        return either_perm and (not obj or self.is_pending_signoff(obj))

    def has_view_permission(self, request, obj=None):
        return (
            super().has_view_permission(request, obj) or
            self.has_signoff_permission(request, obj))

    def has_signoff_permission(self, request, obj=None):
        """ This controls whether the sign-off approve and reject actions are
        available on the change form.  `BlockSubmission.can_user_signoff`
        confirms the current user, who will signoff, is different from the user
        who submitted the guids (unless settings.DEBUG is True when the check
        is ignored)"""
        opts = self.opts
        codename = auth.get_permission_codename('signoff', opts)
        has_perm = request.user.has_perm("%s.%s" % (opts.app_label, codename))
        return has_perm and (not obj or obj.can_user_signoff(request.user))

    def get_fieldsets(self, request, obj):
        input_guids = (
            'Input Guids', {
                'fields': (
                    'input_guids',
                ),
                'classes': ('collapse',)
            })
        block_history = (
            'Block History', {
                'fields': (
                    'block_history',
                )
            }
        )
        if not obj:
            edit_title = 'Add New Blocks'
        elif obj.signoff_state == BlockSubmission.SIGNOFF_PUBLISHED:
            edit_title = 'Blocks Published'
        else:
            edit_title = 'Proposed New Blocks'
        edit = (
            edit_title, {
                'fields': (
                    'blocks',
                    'min_version',
                    'max_version',
                    'url',
                    'reason',
                    'updated_by',
                    'signoff_by',
                    'include_in_legacy',
                    'submission_logs',
                ),
            })

        return (
            (input_guids, edit) if obj else (input_guids, block_history, edit))

    def get_readonly_fields(self, request, obj=None):
        if obj:
            if not self.has_change_permission(request, obj, strict=True):
                ro_fields = admin.utils.flatten_fieldsets(
                    self.get_fieldsets(request, obj))
            else:
                ro_fields = [
                    'blocks',
                    'updated_by',
                    'signoff_by',
                    'submission_logs',
                    'input_guids',
                    'min_version',
                    'max_version',
                    'existing_min_version',
                    'existing_max_version',
                ]
            ro_fields += [
                'existing_min_version',
                'existing_max_version',
            ]
        else:
            ro_fields = (
                'blocks',
                'block_history',
                'updated_by',
                'signoff_by',
                'submission_logs',
            )
        return ro_fields

    @property
    def form(self):
        super_form = super().form
        model_form_fields = {
            'existing_min_version': CharField(
                widget=HiddenInput, required=False),
            'existing_max_version': CharField(
                widget=HiddenInput, required=False)}
        return type(super_form.__name__, (super_form,), model_form_fields)

    def is_single_guid(self, request):
        """We special case a single guid in a few places."""
        return len(self._get_input_guids(request)) == 1

    def _get_input_guids(self, request):
        return splitlines(
            request.POST.get('guids', request.GET.get(
                'guids', request.POST.get('input_guids', ''))))

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        single_guid = self.is_single_guid(request)
        if single_guid and db_field.name in ('min_version', 'max_version'):
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        if not change:
            guids = self._get_input_guids(request)
            if len(guids) == 1:
                block_obj = Block(guid=guids[0])
                form.base_fields['min_version'].choices = _get_version_choices(
                    block_obj, 'min_version')
                form.base_fields['max_version'].choices = _get_version_choices(
                    block_obj, 'max_version')
            form.base_fields['input_guids'].widget = HiddenInput()
        return form

    def add_view(self, request, **kwargs):
        if not self.has_add_permission(request):
            raise PermissionDenied

        MultiBlockForm = self.get_form(request, change=False, **kwargs)
        is_single_guid = self.is_single_guid(request)

        guids_data = request.POST.get('guids', request.GET.get('guids'))
        if guids_data and 'input_guids' not in request.POST:
            # If we get a guids param it's a redirect from input_guids_view.
            initial = {key: values for key, values in request.GET.items()}
            initial.update(**{
                'input_guids': guids_data,
                'existing_min_version': Block.MIN,
                'existing_max_version': Block.MAX})
            form = MultiBlockForm(initial=initial)
        elif request.method == 'POST':
            # Otherwise, if its a POST try to process the form.
            form = MultiBlockForm(request.POST)
            frm_data = form.data
            # Check if the versions specified were the ones we calculated which
            # Blocks would be updated or skipped on.
            # Ignore for a single guid because we always update it irrespective
            # of whether it needs to be updated.
            # TODO: make this more intelligent and don't force a refresh when
            # we have multiple new Blocks (but no existing blocks to update)
            versions_unchanged = is_single_guid or (
                frm_data['min_version'] == frm_data['existing_min_version'] and
                frm_data['max_version'] == frm_data['existing_max_version'])
            if form.is_valid() and versions_unchanged:
                # Save the object so we have the guids
                obj = form.save(commit=False)
                obj.updated_by = request.user
                self.save_model(request, obj, form, change=False)
                self.log_addition(request, obj, [{'added': {}}])
                if '_addanother'in request.POST:
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
            'block_history': self.block_history(
                self.model(input_guids=guids_data)),
            'is_single_guid': is_single_guid,
        }
        context.update(**self._get_enhanced_guid_context(request, guids_data))
        return TemplateResponse(
            request, 'blocklist/block_submission_add_form.html', context)

    def _get_enhanced_guid_context(self, request, guids_data):
        load_full_objects = len(splitlines(guids_data)) <= GUID_FULL_LOAD_LIMIT
        objects = self.model.process_input_guids(
            guids_data,
            v_min=request.POST.get('min_version', Block.MIN),
            v_max=request.POST.get('max_version', Block.MAX),
            load_full_objects=load_full_objects)
        if load_full_objects:
            Block.preload_addon_versions(objects['blocks'])
        return objects

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.model.objects.filter(id=object_id).latest()
        extra_context['has_signoff_permission'] = self.has_signoff_permission(
            request, obj)
        extra_context['has_change_permission_strict'] = (
            self.has_change_permission(request, obj, strict=True))
        extra_context['is_pending_signoff'] = self.is_pending_signoff(obj)
        if obj.signoff_state != BlockSubmission.SIGNOFF_PUBLISHED:
            extra_context.update(
                **self._get_enhanced_guid_context(request, obj.input_guids))
        else:
            extra_context['blocks'] = obj.get_blocks_saved(
                load_full_objects_threshold=GUID_FULL_LOAD_LIMIT)
            if len(extra_context['blocks']) <= GUID_FULL_LOAD_LIMIT:
                # if it's less than the limit we loaded full Block instances
                # so preload the addon_versions so the review links are
                # generated efficiently.
                Block.preload_addon_versions(extra_context['blocks'])
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context)

    def render_change_form(self, request, context, add=False, change=False,
                           form_url='', obj=None):
        if change:
            # add this to the instance so blocks() below can reference it.
            obj._blocks = context['blocks']
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url,
            obj=obj)

    def save_model(self, request, obj, form, change):
        if change and self.is_pending_signoff(obj):
            is_signoff = '_signoff' in request.POST
            is_reject = '_reject' in request.POST
            if ((is_signoff or is_reject) and
                    not self.has_signoff_permission(request, obj)):
                raise PermissionDenied
            if is_signoff:
                obj.signoff_state = BlockSubmission.SIGNOFF_APPROVED
                obj.signoff_by = request.user
            elif is_reject:
                obj.signoff_state = BlockSubmission.SIGNOFF_REJECTED
            elif not self.has_change_permission(request, obj, strict=True):
                # users without full change permission should only do signoff
                raise PermissionDenied

        super().save_model(request, obj, form, change)

        if obj.signoff_state == BlockSubmission.SIGNOFF_PENDING:
            if not obj.needs_signoff():
                obj.update(signoff_state=BlockSubmission.SIGNOFF_NOTNEEDED)

        if obj.is_save_to_blocks_permitted:
            # Then launch a task to async save the individual blocks
            create_blocks_from_multi_block.delay(obj.id)

    def log_change(self, request, obj, message):
        log_entry = None
        is_signoff = '_signoff' in request.POST
        is_reject = '_reject' in request.POST
        if is_signoff:
            signoff_msg = 'Sign-off Approval'
        elif is_reject:
            signoff_msg = 'Sign-off Rejection'
        else:
            signoff_msg = ''

        if not message and signoff_msg:
            # if there's no message (i.e. no changed fields) just use ours.
            log_entry = super().log_change(request, obj, signoff_msg)
        else:
            # otherwise let the message be built as normal
            log_entry = super().log_change(request, obj, message)
            if signoff_msg:
                # before flattening it if we need to add on ours
                log_entry.change_message = (
                    signoff_msg + ' & ' + log_entry.get_change_message())
                log_entry.save()

        return log_entry

    def submission_logs(self, obj):
        content_type = contenttypes.models.ContentType.objects.get_for_model(
            self.model)
        logs = admin.models.LogEntry.objects.filter(
            object_id=obj.id, content_type=content_type)
        return '\n'.join(
            f'{log.action_time.date()}: {str(log)}' for log in logs)

    def blocks(self, obj):
        # Annoyingly, we don't have the full context, but we stashed blocks
        # earlier in render_change_form().
        return render_to_string(
            'blocklist/includes/enhanced_blocks.html',
            {
                'blocks': obj._blocks
            },
        )

    def blocks_count(self, obj):
        return f"{len(obj.to_block)} add-ons"

    def block_history(self, obj):
        guids = splitlines(obj.input_guids)
        if len(guids) != 1:
            return ''
        return format_block_history(
            ActivityLog.objects.for_guidblock(guids[0]).filter(
                action__in=Block.ACTIVITY_IDS).order_by('created'))


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
    change_form_template = 'blocklist/block_change_form.html'

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
            'Edit Block', {
                'fields': (
                    'min_version',
                    'max_version',
                    ('url', 'url_link'),
                    'reason',
                    'include_in_legacy'),
            })

        return (details, history, edit)

    def save_model(self, request, obj, form, change):
        # We don't actually save via this Admin so if we get here something has
        # gone wrong.
        raise PermissionDenied

    def delete_model(self, request, obj):
        block_activity_log_delete(obj, request.user)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            block_activity_log_delete(obj, request.user)
        super().delete_queryset(request, queryset)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        form.base_fields['min_version'].choices = _get_version_choices(
            obj, 'min_version')
        form.base_fields['max_version'].choices = _get_version_choices(
            obj, 'max_version')
        return form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ('min_version', 'max_version'):
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def changeform_view(self, request, obj_id=None, form_url='',
                        extra_context=None):
        if obj_id and request.method == 'POST':
            obj = self.get_object(request, obj_id)
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
            ModelForm = self.get_form(request, obj, change=bool(obj_id))
            form = ModelForm(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                return HttpResponseTemporaryRedirect(
                    reverse('admin:blocklist_blocksubmission_add'))

        return super().changeform_view(
            request, object_id=obj_id, form_url=form_url,
            extra_context=extra_context)
