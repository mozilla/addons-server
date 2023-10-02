from django import http
from django.contrib import admin, auth, contenttypes, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.admin import AMOModelAdmin
from olympia.amo.utils import HttpResponseTemporaryRedirect

from .forms import (
    BlocklistSubmissionForm,
    MultiAddForm,
    MultiDeleteForm,
)
from .models import Block, BlocklistSubmission, BlockVersion
from .tasks import process_blocklistsubmission
from .utils import splitlines


class BlocklistSubmissionStateFilter(admin.SimpleListFilter):
    title = 'Signoff State'
    parameter_name = 'signoff_state'
    default_value = BlocklistSubmission.SIGNOFF_PENDING
    field_choices = BlocklistSubmission.SIGNOFF_STATES.items()
    ALL = 'all'
    DELAYED = 'delayed'

    def lookups(self, request, model_admin):
        return ((self.ALL, 'All'), (self.DELAYED, 'Delayed'), *self.field_choices)

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
        if value == self.ALL:
            return queryset
        elif value == self.DELAYED:
            return queryset.delayed()
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
        warning_message = (
            'The version id:{version_id} could not be selected because {reason}'
        )

        if v_ids := [int(v) for v in request.GET.getlist('v')]:
            submissions = BlocklistSubmission.get_all_submission_versions()
            clashes = set(v_ids) & set(submissions)
            for version_id in clashes:
                messages.add_message(
                    request,
                    messages.WARNING,
                    warning_message.format(
                        version_id=version_id,
                        reason='this version is part of a pending submission',
                    ),
                )
            for block in BlockVersion.objects.filter(version_id__in=v_ids):
                messages.add_message(
                    request,
                    messages.WARNING,
                    warning_message.format(
                        version_id=block.version_id,
                        reason='this version is already blocked',
                    ),
                )

        return redirect(
            reverse('admin:blocklist_blocklistsubmission_add')
            + f'?guids={addon.addonguid_guid}&{request.GET.urlencode()}'
        )


@admin.register(BlocklistSubmission)
class BlocklistSubmissionAdmin(AMOModelAdmin):
    list_display = (
        'blocks_count',
        'action',
        'state',
        'delayed_until',
        'updated_by',
        'modified',
    )
    list_filter = (BlocklistSubmissionStateFilter,)
    ordering = ['-created']
    view_on_site = False
    list_select_related = ('updated_by', 'signoff_by')
    change_form_template = 'admin/blocklist/blocklistsubmission_change_form.html'
    add_form_template = 'admin/blocklist/blocklistsubmission_add_form.html'
    form = BlocklistSubmissionForm

    class Media:
        css = {'all': ('css/admin/blocklist_blocklistsubmission.css',)}
        js = ('js/i18n/en-US.js',)

    def state(self, obj):
        return f'{obj.get_signoff_state_display()}' + (
            ':Delayed' if obj.is_delayed else ''
        )

    state.admin_order_field = '-signoff_state'

    def update_url_value(self, obj):
        return obj.url is None

    def update_reason_value(self, obj):
        return obj.reason is None

    def has_delete_permission(self, request, obj=None):
        # For now, keep all BlocklistSubmission records.
        # TODO: define under what cirumstances records can be safely deleted.
        # https://github.com/mozilla/addons-server/issues/13278
        return False

    def is_approvable(self, obj):
        return obj and obj.signoff_state == BlocklistSubmission.SIGNOFF_PENDING

    def is_changeable(self, obj):
        return obj and obj.signoff_state in (
            BlocklistSubmission.SIGNOFF_PENDING,
            BlocklistSubmission.SIGNOFF_AUTOAPPROVED,
        )

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
        reject_perm = self.has_signoff_reject_permission(request, obj=obj)
        either_perm = change_perm or (reject_perm and not strict)
        return either_perm and (not obj or self.is_changeable(obj))

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
        has_perm = request.user.has_perm(f'{opts.app_label}.{codename}')
        return has_perm and (not obj or obj.can_user_signoff(request.user))

    def has_signoff_reject_permission(self, request, obj=None):
        """This controls whether the sign-off reject action is
        available on the change form.  Users can reject their own submission
        regardless."""
        opts = self.opts
        codename = auth.get_permission_codename('signoff', opts)
        has_perm = request.user.has_perm(f'{opts.app_label}.{codename}')
        is_own_submission = obj and obj.updated_by == request.user
        return has_perm or is_own_submission

    def get_fieldsets(self, request, obj):
        is_new = obj is None
        show_canned = self.has_change_permission(request, obj, strict=True)
        is_delete_submission = not self.is_add_change_submission(request, obj)

        input_guids_section = (
            'Input Guids',
            {
                'fields': (
                    'action',
                    'input_guids',
                ),
                'classes': ('collapse',),
            },
        )

        block_history_section = not is_new and (
            'Block History',
            {'fields': ('block_history',)},
        )

        changed_version_ids_field = (
            'changed_version_ids'
            if self.has_change_permission(request, obj)
            else 'ro_changed_version_ids'
        )

        add_change_section = (
            'Add or Change Blocks',
            {
                'fields': (
                    changed_version_ids_field,
                    'disable_addon',
                    'update_url_value',
                    'url',
                    'update_reason_value',
                    *(('canned_reasons',) if show_canned else ()),
                    'reason',
                    'updated_by',
                    'signoff_by',
                    'submission_logs',
                ),
            },
        )

        delete_section = (
            'Delete Blocks',
            {
                'fields': (
                    changed_version_ids_field,
                    'updated_by',
                    'signoff_by',
                    'submission_logs',
                ),
            },
        )

        delay_section = not is_delete_submission and (
            'Delay',
            {
                'fields': (*(('delay_days',) if is_new else ()), 'delayed_until'),
            },
        )

        sections = (
            input_guids_section,
            block_history_section,
            (add_change_section if not is_delete_submission else delete_section),
            delay_section,
        )
        return tuple(section for section in sections if section)

    def get_readonly_fields(self, request, obj=None):
        ro_fields = [
            'ro_changed_version_ids',
            'updated_by',
            'signoff_by',
            'block_history',
            'submission_logs',
        ]
        if obj:
            ro_fields += [
                'input_guids',
                'action',
            ]
            if not self.has_change_permission(request, obj, strict=True):
                ro_fields += admin.utils.flatten_fieldsets(
                    self.get_fieldsets(request, obj)
                )
        if obj or not self.is_add_change_submission(request, obj):
            ro_fields.append('delay_days')

        return ro_fields

    def _get_input_guids(self, request):
        return splitlines(
            self.get_value(
                'guids', request, default=request.POST.get('input_guids', '')
            )
        )

    def add_view(self, request, **kwargs):
        if not self.has_add_permission(request):
            raise PermissionDenied

        MultiBlockForm = self.get_form(request, change=False, **kwargs)
        is_delete = not self.is_add_change_submission(request, None)
        guids_data = self.get_value('guids', request)
        if guids_data and 'input_guids' not in request.POST:
            # If we get a guids param it's a redirect from input_guids_view.
            initial = {
                key: value
                for key, value in request.GET.items()
                if key not in ('v', 'guids')
            }
            if version_ids := request.GET.getlist('v'):
                # `v` can contain multiple version ids
                try:
                    initial['changed_version_ids'] = [int(v) for v in version_ids]
                except ValueError:
                    pass
            initial.update(**{'input_guids': guids_data})
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
            else:
                guids_data = request.POST.get('input_guids')
        else:
            # if its not a POST and no ?guids there's nothing to do so go back
            return redirect('admin:blocklist_block_add')

        fieldsets = self.get_fieldsets(request, None)
        admin_form = admin.helpers.AdminForm(
            form,
            list(fieldsets),
            self.get_prepopulated_fields(request, None),
            self.get_readonly_fields(request, None),
            model_admin=self,
        )
        context = {
            # standard context django admin expects
            'title': 'Delete Blocks' if is_delete else 'Block Add-ons',
            'subtitle': None,
            'adminform': admin_form,
            'object_id': None,
            'original': None,
            'is_popup': False,
            'to_field': None,
            'media': self.media + admin_form.media,
            'inline_admin_formsets': [],
            'errors': admin.helpers.AdminErrorList(form, []),
            'preserved_filters': self.get_preserved_filters(request),
            # extra context we use in our custom template
            'is_delete': is_delete,
            'block_history': self.block_history(self.model(input_guids=guids_data)),
            'submission_published': False,
        }
        return self.render_change_form(request, context, add=True)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if not obj:
            return self._get_obj_does_not_exist_redirect(
                request, self.model._meta, object_id
            )
        extra_context['can_change_object'] = (
            obj.action == BlocklistSubmission.ACTION_ADDCHANGE
            and self.has_change_permission(request, obj, strict=True)
        )
        extra_context['can_approve'] = self.is_approvable(
            obj
        ) and self.has_signoff_approve_permission(request, obj)
        extra_context['can_reject'] = self.is_changeable(
            obj
        ) and self.has_signoff_reject_permission(request, obj)
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url='', obj=None
    ):
        if obj:
            # add this to the instance so ro_changed_version_ids() can reference it.
            obj._blocks = context['adminform'].form.blocks
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def save_model(self, request, obj, form, change):
        if change and self.is_changeable(obj):
            is_approve = '_approve' in request.POST
            is_reject = '_reject' in request.POST
            if is_approve and self.is_approvable(obj):
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

        obj.update_signoff_for_auto_approval()

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

    def ro_changed_version_ids(self, obj):
        # Annoyingly, we don't have the full context, but we stashed blocks
        # earlier in render_change_form().
        published = obj.signoff_state == obj.SIGNOFF_PUBLISHED
        total_adu = sum(
            (bl.current_adu if not published else bl.average_daily_users_snapshot) or 0
            for bl in obj._blocks
        )

        return render_to_string(
            'admin/blocklist/includes/blocks.html',
            {'blocks': obj._blocks, 'instance': obj, 'total_adu': total_adu},
        )

    ro_changed_version_ids.short_description = 'Changed version ids'

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
class BlockAdmin(BlockAdminAddMixin, AMOModelAdmin):
    list_display = ('guid', 'updated_by', 'modified')
    readonly_fields = (
        'addon_guid',
        'addon_name',
        'addon_updated',
        'users',
        'review_listed_link',
        'review_unlisted_link',
        'block_history',
        'url_link',
        'blocked_versions',
    )
    ordering = ['-modified']
    view_on_site = False
    list_select_related = ('updated_by',)
    change_list_template = 'admin/blocklist/block_change_list.html'
    change_form_template = 'admin/blocklist/block_change_form.html'

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

    def blocked_versions(self, obj):
        return ', '.join(
            sorted(obj.blockversion_set.values_list('version__version', flat=True))
        )

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
                    'blocked_versions',
                    ('url', 'url_link'),
                    'reason',
                ),
            },
        )

        return (details, history, edit)

    def has_change_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # We don't save via this Admin so if we get here something has gone
        # wrong.
        raise PermissionDenied

    def delete_model(self, request, obj):
        # We don't delete via this Admin so if we get here something has gone
        # wrong.
        raise PermissionDenied

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
