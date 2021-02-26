from django import http
from django.contrib import admin, auth, contenttypes, messages
from django.core.exceptions import PermissionDenied
from django.forms.fields import ChoiceField
from django.forms.widgets import HiddenInput
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext

import waffle

from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.utils import HttpResponseTemporaryRedirect
from olympia.versions.models import Version

from .forms import BlockForm, BlocklistSubmissionForm, MultiAddForm, MultiDeleteForm
from .models import Block, BlocklistSubmission
from .tasks import process_blocklistsubmission
from .utils import splitlines


# The limit for how many GUIDs should be fully loaded with all metadata
GUID_FULL_LOAD_LIMIT = 100


def _get_version_choices(block, field_name):
    # field_name will be `min_version` or `max_version`
    default = block._meta.get_field(field_name).default
    choices = [(default, default)] + list(
        (version.version, version.version) for version in block.addon_versions
    )
    block_version = getattr(block, field_name)
    if block_version and (block_version, block_version) not in choices:
        # if the current version isn't in choices it's not a valid version of
        # the addon.  This is either because:
        # - the Block was created as a multiple submission so was a free input
        # - it's a new Block and the min|max_version was passed as a GET param
        # - the version was hard-deleted from the addon afterwards (unlikely)
        choices = [(block_version, '(invalid)')] + choices
    return choices


class BlocklistSubmissionStateFilter(admin.SimpleListFilter):
    title = gettext('Signoff State')
    parameter_name = 'signoff_state'
    default_value = BlocklistSubmission.SIGNOFF_PENDING
    field_choices = BlocklistSubmission.SIGNOFF_STATES.items()

    def lookups(self, request, model_admin):
        return (('all', 'All'), *self.field_choices)

    def choices(self, cl):
        value = self.value()
        for lookup, title in self.lookup_choices:
            selected = (
                lookup == self.default_value if value is None else value == str(lookup)
            )
            yield {
                'selected': selected,
                'query_string': cl.get_query_string({self.parameter_name: lookup}, []),
                'display': title,
            }

    def queryset(self, request, queryset):
        value = self.value()
        if value == 'all':
            return queryset
        real_value = self.default_value if value is None else value
        return queryset.filter(**{self.parameter_name: real_value})


class BlockAdminAddMixin:
    def get_urls(self):
        my_urls = [
            path(
                'delete_multiple/',
                self.admin_site.admin_view(self.delete_multiple_view),
                name='blocklist_block_delete_multiple',
            ),
            path(
                'add_addon/<path:pk>/',
                self.admin_site.admin_view(self.add_from_addon_pk_view),
                name='blocklist_block_addaddon',
            ),
        ]
        return my_urls + super().get_urls()

    def add_view(self, request, form_url='', extra_context=None):
        return self._multi_input_view(
            request, add=True, form_url=form_url, extra_context=extra_context
        )

    def delete_multiple_view(self, request, form_url='', extra_context=None):
        return self._multi_input_view(
            request, add=False, form_url=form_url, extra_context=extra_context
        )

    def _multi_input_view(self, request, *, add, form_url='', extra_context=None):
        MultiForm = MultiAddForm if add else MultiDeleteForm
        if request.method == 'POST':
            form = MultiForm(request.POST)
            if form.is_valid():
                guids = splitlines(form.data.get('guids'))
                if len(guids) == 1 and form.existing_block:
                    # If the guid already has a Block go to the change view
                    return redirect(
                        'admin:blocklist_block_change', form.existing_block.id
                    )
                elif len(guids) > 0:
                    # Otherwise go to multi view.
                    return HttpResponseTemporaryRedirect(
                        reverse('admin:blocklist_blocklistsubmission_add')
                    )
        else:
            form = MultiForm()

        context = {
            'form': form,
            'add': add,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, None),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': 'Block Add-ons' if add else 'Delete Blocks',
            'save_as': False,
        }
        return TemplateResponse(
            request, 'admin/blocklist/multi_guid_input.html', context
        )

    def add_from_addon_pk_view(self, request, pk, **kwargs):
        addon = get_object_or_404(Addon.unfiltered, pk=pk or kwargs.get('pk'))
        get_params = request.GET.copy()
        for key in ('min', 'max'):
            if key in get_params:
                version = get_object_or_404(
                    Version.unfiltered, pk=get_params.pop(key)[0]
                )
                get_params[f'{key}_version'] = version.version

        if 'min_version' in get_params or 'max_version' in get_params:
            warning_message = (
                f"The versions {get_params.get('min_version', '0')} to "
                f"{get_params.get('max_version', '*')} could not be "
                'pre-selected because {reason}'
            )
        else:
            warning_message = None

        if addon.blocklistsubmission:
            if 'min_version' in get_params or 'max_version' in get_params:
                messages.add_message(
                    request,
                    messages.WARNING,
                    warning_message.format(
                        reason='this addon is part of a pending submission'
                    ),
                )
            return redirect(
                reverse(
                    'admin:blocklist_blocklistsubmission_change',
                    args=(addon.blocklistsubmission.pk,),
                )
            )
        elif addon.block:
            if 'min_version' in get_params or 'max_version' in get_params:
                messages.add_message(
                    request,
                    messages.WARNING,
                    warning_message.format(
                        reason='some versions have been blocked already'
                    ),
                )
            return redirect(
                reverse('admin:blocklist_block_change', args=(addon.block.pk,))
            )
        else:
            return redirect(
                reverse('admin:blocklist_blocklistsubmission_add')
                + f'?guids={addon.addonguid_guid}&{get_params.urlencode()}'
            )


@admin.register(BlocklistSubmission)
class BlocklistSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'blocks_count',
        'action',
        'signoff_state',
        'updated_by',
        'modified',
    )
    list_filter = (BlocklistSubmissionStateFilter,)
    ordering = ['-created']
    view_on_site = False
    list_select_related = ('updated_by', 'signoff_by')
    change_form_template = 'admin/blocklist/blocklistsubmission_change_form.html'
    form = BlocklistSubmissionForm

    class Media:
        css = {'all': ('css/admin/blocklist_blocklistsubmission.css',)}
        js = ('js/i18n/en-US.js',)

    def has_delete_permission(self, request, obj=None):
        # For now, keep all BlocklistSubmission records.
        # TODO: define under what cirumstances records can be safely deleted.
        # https://github.com/mozilla/addons-server/issues/13278
        return False

    def is_pending_signoff(self, obj):
        return obj and obj.signoff_state == BlocklistSubmission.SIGNOFF_PENDING

    def get_value(self, name, request, obj=None, default=None):
        """Gets the named property from the obj if provided, or POST or GET."""
        return (
            getattr(obj, name, default)
            if obj
            else request.POST.get(name, request.GET.get(name, default))
        )

    def is_add_change_submission(self, request, obj):
        return str(self.get_value('action', request, obj, 0)) == str(
            BlocklistSubmission.ACTION_ADDCHANGE
        )

    def has_change_permission(self, request, obj=None, strict=False):
        """While a block submission is pending we want it to be partially
        editable (the url and reason).  Once it's been rejected or approved it
        can't be changed though.  Normally, as sign-off uses the changeform,
        we need to return true if the user has sign-off permission instead.
        We can override that permissive behavior with `strict=True`."""
        change_perm = super().has_change_permission(request, obj=obj)
        approve_perm = self.has_signoff_approve_permission(request, obj=obj)
        either_perm = change_perm or (approve_perm and not strict)
        return either_perm and (not obj or self.is_pending_signoff(obj))

    def has_view_permission(self, request, obj=None):
        return (
            super().has_view_permission(request, obj)
            or self.has_signoff_approve_permission(request, obj)
            or self.has_signoff_reject_permission(request, obj)
        )

    def has_signoff_approve_permission(self, request, obj=None):
        """This controls whether the sign-off approve action is
        available on the change form.  `BlocklistSubmission.can_user_signoff`
        confirms the current user, who will signoff, is different from the user
        who submitted the guids (unless settings.DEBUG is True when the check
        is ignored)"""
        opts = self.opts
        codename = auth.get_permission_codename('signoff', opts)
        has_perm = request.user.has_perm('%s.%s' % (opts.app_label, codename))
        return has_perm and (not obj or obj.can_user_signoff(request.user))

    def has_signoff_reject_permission(self, request, obj=None):
        """This controls whether the sign-off reject action is
        available on the change form.  Users can reject their own submission
        regardless."""
        opts = self.opts
        codename = auth.get_permission_codename('signoff', opts)
        has_perm = request.user.has_perm('%s.%s' % (opts.app_label, codename))
        is_own_submission = obj and obj.updated_by == request.user
        return has_perm or is_own_submission

    def get_fieldsets(self, request, obj):
        input_guids = (
            'Input Guids',
            {
                'fields': (
                    'action',
                    'input_guids',
                ),
                'classes': ('collapse',),
            },
        )
        block_history = ('Block History', {'fields': ('block_history',)})
        if not obj:
            edit_title = 'Add New Blocks'
        elif obj.signoff_state == BlocklistSubmission.SIGNOFF_PUBLISHED:
            edit_title = 'Blocks Published'
        else:
            edit_title = 'Proposed New Blocks'

        add_change = (
            edit_title,
            {
                'fields': (
                    'blocks',
                    'min_version',
                    'max_version',
                    'url',
                    'reason',
                    'updated_by',
                    'signoff_by',
                    'legacy_id',
                    'submission_logs',
                ),
            },
        )

        delete = (
            'Delete Blocks',
            {
                'fields': (
                    'blocks',
                    'updated_by',
                    'signoff_by',
                    'submission_logs',
                ),
            },
        )

        if self.is_add_change_submission(request, obj):
            return (
                (input_guids, add_change)
                if obj
                else (input_guids, block_history, add_change)
            )
        else:
            return (
                (input_guids, delete) if obj else (input_guids, block_history, delete)
            )

    def get_readonly_fields(self, request, obj=None):
        ro_fields = [
            'blocks',
            'updated_by',
            'signoff_by',
            'block_history',
            'submission_logs',
        ]
        if not waffle.switch_is_active('blocklist_legacy_submit'):
            ro_fields.append('legacy_id')
        if obj:
            ro_fields += [
                'input_guids',
                'action',
                'min_version',
                'max_version',
                'existing_min_version',
                'existing_max_version',
            ]
            if not self.has_change_permission(request, obj, strict=True):
                ro_fields += admin.utils.flatten_fieldsets(
                    self.get_fieldsets(request, obj)
                )

        return ro_fields

    def _get_input_guids(self, request):
        return splitlines(
            self.get_value(
                'guids', request, default=request.POST.get('input_guids', '')
            )
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        single_guid = len(self._get_input_guids(request)) == 1
        if single_guid and db_field.name in ('min_version', 'max_version'):
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        if not change:
            guids = self._get_input_guids(request)
            if len(guids) == 1:
                block_obj = Block(guid=guids[0])
                if 'min_version' in form.base_fields:
                    form.base_fields['min_version'].choices = _get_version_choices(
                        block_obj, 'min_version'
                    )
                    form.base_fields['max_version'].choices = _get_version_choices(
                        block_obj, 'max_version'
                    )
            form.base_fields['input_guids'].widget = HiddenInput()
            form.base_fields['action'].widget = HiddenInput()
        return form

    def add_view(self, request, **kwargs):
        if not self.has_add_permission(request):
            raise PermissionDenied

        MultiBlockForm = self.get_form(request, change=False, **kwargs)
        is_delete = not self.is_add_change_submission(request, None)

        guids_data = self.get_value('guids', request)
        if guids_data and 'input_guids' not in request.POST:
            # If we get a guids param it's a redirect from input_guids_view.
            initial = {key: values for key, values in request.GET.items()}
            initial.update(
                **{
                    'input_guids': guids_data,
                    'existing_min_version': initial.get('min_version', Block.MIN),
                    'existing_max_version': initial.get('max_version', Block.MAX),
                }
            )
            if 'action' in request.POST:
                initial['action'] = request.POST['action']
            form = MultiBlockForm(initial=initial)
        elif request.method == 'POST':
            # Otherwise, if its a POST try to process the form.
            form = MultiBlockForm(request.POST)
            if form.is_valid():
                # Save the object so we have the guids
                obj = form.save(commit=False)
                obj.updated_by = request.user
                self.save_model(request, obj, form, change=False)
                self.log_addition(request, obj, [{'added': {}}])
                return self.response_add(request, obj)
            elif not is_delete:
                guids_data = request.POST.get('input_guids')
                form_data = form.data.copy()
                # each time we render the form we pass along the existing
                # versions so we can detect if they've been changed and we'd '
                # need a recalculation how existing blocks are affected.
                form_data['existing_min_version'] = form_data['min_version']
                form_data['existing_max_version'] = form_data['max_version']
                form.data = form_data
        else:
            # if its not a POST and no ?guids there's nothing to do so go back
            return redirect('admin:blocklist_block_add')
        context = {
            'form': form,
            'fieldsets': self.get_fieldsets(request, None),
            'add': True,
            'change': False,
            'has_view_permission': self.has_view_permission(request, None),
            'has_add_permission': self.has_add_permission(request),
            'app_label': 'blocklist',
            'opts': self.model._meta,
            'title': 'Delete Blocks' if is_delete else 'Block Add-ons',
            'save_as': False,
            'block_history': self.block_history(self.model(input_guids=guids_data)),
            'submission_complete': False,
        }
        context.update(**self._get_enhanced_guid_context(request, guids_data))
        return TemplateResponse(
            request, 'admin/blocklist/blocklistsubmission_add_form.html', context
        )

    def _get_enhanced_guid_context(self, request, guids_data, obj=None):
        load_full_objects = len(splitlines(guids_data)) <= GUID_FULL_LOAD_LIMIT
        objects = self.model.process_input_guids(
            guids_data,
            v_min=self.get_value('min_version', request, obj, Block.MIN),
            v_max=self.get_value('max_version', request, obj, Block.MAX),
            load_full_objects=load_full_objects,
            filter_existing=self.is_add_change_submission(request, obj),
        )
        if load_full_objects:
            Block.preload_addon_versions(objects['blocks'])
        objects['is_imported_from_legacy_regex'] = [
            obj.guid for obj in objects['blocks'] if obj.is_imported_from_legacy_regex
        ]
        return objects

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if not obj:
            return self._get_obj_does_not_exist_redirect(
                request, self.model._meta, object_id
            )
        extra_context[
            'has_signoff_approve_permission'
        ] = self.has_signoff_approve_permission(request, obj)
        extra_context[
            'has_signoff_reject_permission'
        ] = self.has_signoff_reject_permission(request, obj)
        extra_context['can_change_object'] = (
            obj.action == BlocklistSubmission.ACTION_ADDCHANGE
            and self.has_change_permission(request, obj, strict=True)
        )
        extra_context['is_pending_signoff'] = self.is_pending_signoff(obj)
        if obj.signoff_state != BlocklistSubmission.SIGNOFF_PUBLISHED:
            extra_context.update(
                **self._get_enhanced_guid_context(request, obj.input_guids, obj)
            )
        else:
            extra_context['blocks'] = obj.get_blocks_submitted(
                load_full_objects_threshold=GUID_FULL_LOAD_LIMIT
            )
            if len(extra_context['blocks']) <= GUID_FULL_LOAD_LIMIT:
                # if it's less than the limit we loaded full Block instances
                # so preload the addon_versions so the review links are
                # generated efficiently.
                Block.preload_addon_versions(extra_context['blocks'])
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url='', obj=None
    ):
        if change:
            # add this to the instance so blocks() below can reference it.
            obj._blocks = context['blocks']
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def save_model(self, request, obj, form, change):
        if change and self.is_pending_signoff(obj):
            is_approve = '_approve' in request.POST
            is_reject = '_reject' in request.POST
            if is_approve:
                if not self.has_signoff_approve_permission(request, obj):
                    raise PermissionDenied
                obj.signoff_state = BlocklistSubmission.SIGNOFF_APPROVED
                obj.signoff_by = request.user
            elif is_reject:
                if not self.has_signoff_reject_permission(request, obj):
                    raise PermissionDenied
                obj.signoff_state = BlocklistSubmission.SIGNOFF_REJECTED
            elif not self.has_change_permission(request, obj, strict=True):
                # users without full change permission should only do signoff
                raise PermissionDenied

        super().save_model(request, obj, form, change)

        obj.update_if_signoff_not_needed()

        if obj.is_submission_ready:
            # Then launch a task to async save the individual blocks
            process_blocklistsubmission.delay(obj.id)

    def log_change(self, request, obj, message):
        log_entry = None
        is_approve = '_approve' in request.POST
        is_reject = '_reject' in request.POST
        if is_approve:
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
                    signoff_msg + ' & ' + log_entry.get_change_message()
                )
                log_entry.save()

        return log_entry

    def submission_logs(self, obj):
        content_type = contenttypes.models.ContentType.objects.get_for_model(self.model)
        logs = admin.models.LogEntry.objects.filter(
            object_id=obj.id, content_type=content_type
        )
        return '\n'.join(f'{log.action_time.date()}: {str(log)}' for log in logs)

    def blocks(self, obj):
        # Annoyingly, we don't have the full context, but we stashed blocks
        # earlier in render_change_form().
        complete = obj.signoff_state == BlocklistSubmission.SIGNOFF_PUBLISHED
        return render_to_string(
            'admin/blocklist/includes/enhanced_blocks.html',
            {
                'blocks': obj._blocks,
                'submission_complete': complete,
            },
        )

    def blocks_count(self, obj):
        return f'{len(obj.to_block)} add-ons'

    def block_history(self, obj):
        guids = splitlines(obj.input_guids)
        if len(guids) != 1:
            return ''
        logs = (
            ActivityLog.objects.for_guidblock(guids[0])
            .filter(action__in=Block.ACTIVITY_IDS)
            .order_by('created')
        )
        return render_to_string('admin/blocklist/includes/logs.html', {'logs': logs})


@admin.register(Block)
class BlockAdmin(BlockAdminAddMixin, admin.ModelAdmin):
    list_display = ('guid', 'min_version', 'max_version', 'updated_by', 'modified')
    _readonly_fields = (
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
    change_list_template = 'admin/blocklist/block_change_list.html'
    change_form_template = 'admin/blocklist/block_change_form.html'
    form = BlockForm

    class Media:
        css = {'all': ('css/admin/blocklist_block.css',)}
        js = ('js/i18n/en-US.js',)

    def addon_guid(self, obj):
        return obj.guid

    addon_guid.short_description = 'Add-on GUID'

    def addon_name(self, obj):
        return obj.addon.name

    def addon_updated(self, obj):
        return obj.addon.modified

    def users(self, obj):
        return obj.average_daily_users_snapshot

    def block_history(self, obj):
        logs = (
            ActivityLog.objects.for_guidblock(obj.guid)
            .filter(action__in=Block.ACTIVITY_IDS)
            .order_by('created')
        )
        submission = obj.active_submissions.last()
        return render_to_string(
            'admin/blocklist/includes/logs.html',
            {
                'logs': logs,
                'blocklistsubmission': submission,
                'blocklistsubmission_changes': submission.get_changes_from_block(obj)
                if submission
                else {},
            },
        )

    def url_link(self, obj):
        return format_html('<a href="{}">{}</a>', obj.url, obj.url)

    def get_fieldsets(self, request, obj):
        details = (
            None,
            {
                'fields': (
                    'addon_guid',
                    'addon_name',
                    'addon_updated',
                    'users',
                    ('review_listed_link', 'review_unlisted_link'),
                )
            },
        )
        history = ('Block History', {'fields': ('block_history',)})
        edit = (
            'Edit Block',
            {
                'fields': (
                    'min_version',
                    'max_version',
                    ('url', 'url_link'),
                    'reason',
                    'legacy_id',
                ),
            },
        )

        return (details, history, edit)

    def get_readonly_fields(self, request, obj=None):
        fields = list(self._readonly_fields)
        if not waffle.switch_is_active('blocklist_legacy_submit'):
            fields.append('legacy_id')
        return fields

    def has_change_permission(self, request, obj=None):
        if obj and obj.is_readonly:
            return False
        else:
            return super().has_change_permission(request, obj=obj)

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_readonly:
            return False
        else:
            return super().has_delete_permission(request, obj=obj)

    def save_model(self, request, obj, form, change):
        # We don't save via this Admin so if we get here something has gone
        # wrong.
        raise PermissionDenied

    def delete_model(self, request, obj):
        # We don't delete via this Admin so if we get here something has gone
        # wrong.
        raise PermissionDenied

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        if 'min_version' in form.base_fields:
            form.base_fields['min_version'].choices = _get_version_choices(
                obj, 'min_version'
            )
            form.base_fields['max_version'].choices = _get_version_choices(
                obj, 'max_version'
            )
        return form

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in ('min_version', 'max_version'):
            return ChoiceField(**kwargs)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def changeform_view(self, request, obj_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        if obj_id:
            obj = (
                self.get_object(request, obj_id)
                # if we can't find the obj_id maybe it's a guid instead
                or self.get_object(request, obj_id, 'guid')
            )
            if obj and str(obj_id) != str(obj.id):
                # we found it from the guid if the obj_id != obj.id so redirect
                url = request.path.replace(obj_id, str(obj.id), 1)
                return http.HttpResponsePermanentRedirect(url)
        else:
            obj = None
        if obj and request.method == 'POST':
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
            ModelForm = self.get_form(request, obj, change=bool(obj_id))
            form = ModelForm(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                return HttpResponseTemporaryRedirect(
                    reverse('admin:blocklist_blocklistsubmission_add')
                )

        extra_context['show_save_and_continue'] = False
        extra_context['is_imported_from_legacy_regex'] = (
            obj and obj.is_imported_from_legacy_regex
        )

        return super().changeform_view(
            request, object_id=obj_id, form_url=form_url, extra_context=extra_context
        )

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if not self.has_delete_permission(request, obj):
            raise PermissionDenied
        return redirect(
            reverse('admin:blocklist_blocklistsubmission_add')
            + f'?guids={obj.guid}&action={BlocklistSubmission.ACTION_DELETE}'
        )
