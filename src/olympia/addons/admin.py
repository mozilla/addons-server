from urllib.parse import urlencode, urljoin

from django import forms, http
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.utils import display_for_field
from django.core import validators
from django.db.models import Exists, OuterRef
from django.forms.models import modelformset_factory
from django.urls import resolve, reverse
from django.utils.html import format_html, format_html_join

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonListingInfo, AddonReviewerFlags, AddonUser
from olympia.amo.admin import AMOModelAdmin, DateRangeFilter
from olympia.amo.forms import AMOModelForm
from olympia.amo.templatetags.jinja_helpers import vite_asset
from olympia.amo.utils import send_mail
from olympia.discovery.admin import DiscoveryAddon
from olympia.files.models import File
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview
from olympia.versions.models import Version
from olympia.zadmin.admin import related_content_link, related_single_content_link

from . import models
from .forms import AdminBaseFileFormSet, FileStatusForm


log = olympia.core.logger.getLogger('z.addons.admin')


class AddonReviewerFlagsInline(admin.TabularInline):
    model = AddonReviewerFlags
    verbose_name_plural = 'Reviewer Flags'
    can_delete = False
    view_on_site = False


class AddonListingInfoInline(admin.TabularInline):
    model = AddonListingInfo
    can_delete = False
    view_on_site = False


class AddonUserBase:
    model = AddonUser
    raw_id_fields = (
        'addon',
        'user',
    )
    fields = (
        'addon',
        'user',
        'role',
        'listed',
        'position',
        'user_profile_link',
    )
    readonly_fields = ('user_profile_link',)
    extra = 0

    def user_profile_link(self, obj):
        if obj.pk:
            return format_html(
                '<a href="{}">Admin User Profile</a> ({})',
                reverse('admin:users_userprofile_change', args=(obj.user.pk,)),
                obj.user.email,
            )
        else:
            return ''

    user_profile_link.short_description = 'User Profile'


class AddonUserAdmin(AddonUserBase, AMOModelAdmin):
    readonly_fields = AddonUserBase.readonly_fields + (
        'addon',
        'user',
    )


class AddonUserInline(AddonUserBase, admin.TabularInline):
    pass


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
        'created',
        'version__id',
        'version__version',
        'version__channel',
        'version__deleted',
        'status',
        'is_signed',
        'version__is_blocked',
        'version__needs_human_review',
    )
    editable_fields = ('status',)
    readonly_fields = tuple(set(fields) - set(editable_fields))
    can_delete = False
    view_on_site = False
    template = 'admin/addons/file_inline.html'
    checks_class = FileInlineChecks
    show_change_link = True

    def version__id(self, obj):
        return obj.version_id

    version__id.short_description = 'Version ID'

    def version__version(self, obj):
        return related_single_content_link(obj, 'version')

    version__version.short_description = 'Version'

    def version__channel(self, obj):
        return obj.version.get_channel_display()

    version__channel.short_description = 'Channel'

    def version__deleted(self, obj):
        return obj.version.deleted

    version__deleted.short_description = 'Deleted'
    version__deleted.boolean = True

    def version__is_blocked(self, obj):
        blockversion = getattr(obj.version, 'blockversion', None)
        if not blockversion:
            return ''
        url = blockversion.block.get_admin_url_path()
        template = '<a href="{}">Blocked</a>'
        return format_html(template, url)

    version__is_blocked.short_description = 'Block status'

    def version__needs_human_review(self, obj):
        # Set by the prefetch_related() call below.
        return obj.needs_human_review

    version__needs_human_review.short_description = 'Needs human review'
    version__needs_human_review.boolean = True

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
            Version.unfiltered.filter(addon=self.instance).values_list('pk', flat=True),
            30,
        )
        # A list coercion so this doesn't result in a subquery with a LIMIT
        # which MySQL doesn't support (at this time).
        versions = list(self.pager.object_list)
        qs = (
            super()
            .get_queryset(request)
            .filter(version__in=versions)
            .order_by('-version__id')
        )
        sub_qs = NeedsHumanReview.objects.filter(
            is_active=True, version=OuterRef('version')
        )
        return qs.select_related('version', 'version__blockversion').annotate(
            needs_human_review=Exists(sub_qs)
        )


class AddonAdmin(AMOModelAdmin):
    class Media:
        css = {'all': (vite_asset('css/admin-addon.less'),)}
        js = (
            # TODO: This is probably a redundant dependency
            'admin/js/jquery.init.js',
            vite_asset('js/admin-addon.js'),
        )

    list_display = (
        '__str__',
        'type',
        'guid',
        'status',
        'average_daily_users',
        'average_rating',
        'authors_links',
        'reviewer_links',
        'reviewer_flags',
    )
    list_filter = (
        (
            'created',
            DateRangeFilter,
        ),
        'type',
        'status',
        (
            'addonuser__user__created',
            DateRangeFilter,
        ),
        (
            'addonuser__user__banned',
            admin.EmptyFieldListFilter,
        ),
        (
            'reviewerflags__auto_approval_disabled',
            admin.BooleanFieldListFilter,
        ),
        (
            'reviewerflags__auto_approval_disabled_unlisted',
            admin.BooleanFieldListFilter,
        ),
        (
            'reviewerflags__auto_approval_disabled_until_next_approval',
            admin.BooleanFieldListFilter,
        ),
        (
            'reviewerflags__auto_approval_disabled_until_next_approval_unlisted',
            admin.BooleanFieldListFilter,
        ),
        (
            'reviewerflags__auto_approval_delayed_until',
            DateRangeFilter,
        ),
        (
            'reviewerflags__auto_approval_delayed_until_unlisted',
            DateRangeFilter,
        ),
    )
    list_select_related = ('reviewerflags',)
    search_fields = ('id', 'guid__startswith', 'slug__startswith')
    search_by_ip_actions = (amo.LOG.ADD_VERSION.id,)
    search_by_ip_activity_accessor = 'addonlog__activity_log'
    search_by_ip_activity_reverse_accessor = 'activity_log__addonlog__addon'
    inlines = (
        AddonReviewerFlagsInline,
        AddonUserInline,
        FileInline,
        AddonListingInfoInline,
    )
    readonly_fields = (
        'id',
        'created',
        'type',
        'activity',
        'discovery_addon',
        'average_rating',
        'bayesian_rating',
        'guid',
        'total_ratings_link',
        'text_ratings_count',
        'weekly_downloads',
        'average_daily_users',
        'hotness',
    )

    fieldsets = (
        (
            None,
            {
                'fields': (
                    'id',
                    'created',
                    'name',
                    'slug',
                    'guid',
                    'default_locale',
                    'type',
                    'status',
                    'activity',
                    'discovery_addon',
                ),
            },
        ),
        (
            'Details',
            {
                'fields': (
                    'summary',
                    'description',
                    'homepage',
                    'eula',
                    'privacy_policy',
                    'developer_comments',
                    'icon_type',
                ),
            },
        ),
        (
            'Support',
            {
                'fields': ('support_url', 'support_email'),
            },
        ),
        (
            'Stats',
            {
                'fields': (
                    'total_ratings_link',
                    'average_rating',
                    'bayesian_rating',
                    'text_ratings_count',
                    'weekly_downloads',
                    'average_daily_users',
                    'hotness',
                ),
            },
        ),
        (
            'Flags',
            {
                'fields': (
                    'disabled_by_user',
                    'requires_payment',
                    'is_experimental',
                    'reputation',
                ),
            },
        ),
        (
            'Dictionaries and Language Packs',
            {
                'fields': ('target_locale',),
            },
        ),
    )

    def get_queryset_annotations(self):
        # Add annotation for _unlisted_versions_exists/_listed_versions_exists
        # to avoid repeating those queries for each add-on in the list.
        sub_qs = Version.unfiltered.filter(addon=OuterRef('pk')).values_list('id')
        annotations = {
            '_unlisted_versions_exists': Exists(
                sub_qs.filter(channel=amo.CHANNEL_UNLISTED)
            ),
            '_listed_versions_exists': Exists(
                sub_qs.filter(channel=amo.CHANNEL_LISTED)
            ),
        }
        return annotations

    def get_queryset(self, request):
        return (
            Addon.unfiltered.all()
            .only_translations()
            .transform(Addon.attach_all_authors)
        )

    def get_rangefilter_addonuser__user__created_title(self, request, field_path):
        return 'author created'

    def authors_links(self, obj):
        # Note: requires .transform(Addon.attach_all_authors) to have been
        # applied to fill all_authors property and role on each user in it.
        authors = obj.all_authors
        return (
            format_html(
                '<ul>{}</ul>',
                format_html_join(
                    '',
                    '<li><a href="{}">{} ({}{})</a></li>',
                    (
                        (
                            urljoin(
                                settings.EXTERNAL_SITE_URL,
                                reverse(
                                    'admin:users_userprofile_change', args=(author.pk,)
                                ),
                            ),
                            author.email,
                            dict(amo.AUTHOR_CHOICES_UNFILTERED)[author.role],
                            ', Not listed' if author.listed is False else '',
                        )
                        for author in authors
                    ),
                ),
            )
            if authors
            else '-'
        )

    authors_links.short_description = 'Authors'

    def total_ratings_link(self, obj):
        return related_content_link(
            obj,
            Rating,
            'addon',
            related_manager='without_replies',
            text=obj.total_ratings,
        )

    total_ratings_link.short_description = 'Ratings'

    def reviewer_links(self, obj):
        links = []
        # _has_listed_versions_exists and _has_unlisted_versions_exists are
        # provided by annotations made in get_queryset()
        if obj._listed_versions_exists:
            links.append(
                (
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['listed', obj.id]),
                    ),
                    'Review (listed)',
                )
            )
        if obj._unlisted_versions_exists:
            links.append(
                (
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['unlisted', obj.id]),
                    ),
                    'Review (unlisted)',
                )
            )
        return format_html(
            '<ul>{}</ul>', format_html_join('', '<li><a href="{}">{}</a></li>', links)
        )

    reviewer_links.short_description = 'Reviewer links'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        lookup_field = Addon.get_lookup_field(object_id)
        if lookup_field != 'pk':
            addon = None
            try:
                if lookup_field in ('slug', 'guid'):
                    addon = self.get_queryset(request).get(**{lookup_field: object_id})
            except Addon.DoesNotExist as exc:
                raise http.Http404 from exc
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon and addon.id and addon.id != object_id:
                url = request.path.replace(object_id, str(addon.id), 1)
                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)

        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url='', obj=None
    ):
        context.update(
            {
                'external_site_url': settings.EXTERNAL_SITE_URL,
                'has_listed_versions': obj.has_listed_versions(include_deleted=True)
                if obj
                else False,
                'has_unlisted_versions': obj.has_unlisted_versions(include_deleted=True)
                if obj
                else False,
            }
        )

        return super().render_change_form(
            request=request,
            context=context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if 'status' in form.changed_data:
            ActivityLog.objects.create(
                amo.LOG.CHANGE_STATUS, obj, form.cleaned_data['status']
            )
            log.info(
                'Addon "%s" status changed to: %s'
                % (obj.slug, form.cleaned_data['status'])
            )

    @admin.display(description='Activity Logs')
    def activity(self, obj):
        return related_content_link(obj, ActivityLog, 'addonlog__addon')

    @admin.display(description='Flags')
    def reviewer_flags(self, obj):
        fields = (
            field
            for field in AddonReviewerFlags._meta.get_fields()
            if field.name not in ('created', 'modified', 'addon')
        )
        try:
            contents = (
                (
                    field.verbose_name,
                    display_for_field(
                        getattr(obj.reviewerflags, field.name), field, False
                    ),
                )
                for field in fields
                if getattr(obj.reviewerflags, field.name)
            )
            if contents:
                return format_html(
                    '<table>{}</table>',
                    format_html_join(
                        '',
                        '<tr class="alt"><th>{}</th><td>{}</td></tr>',
                        contents,
                    ),
                )
        except AddonReviewerFlags.DoesNotExist:
            pass

    @admin.display(description='Discovery Addon')
    def discovery_addon(self, obj):
        url = reverse(
            'admin:{}_{}_change'.format(
                DiscoveryAddon._meta.app_label, DiscoveryAddon._meta.model_name
            ),
            args=[obj.pk],
        )
        return format_html('<a href="{}">Discovery Addon</a>', url)


class FrozenAddonAdmin(AMOModelAdmin):
    raw_id_fields = ('addon',)


class ReplacementAddonForm(AMOModelForm):
    def clean_path(self):
        path = None
        try:
            path = self.data.get('path')
            site = settings.SITE_URL
            if models.ReplacementAddon.path_is_external(path):
                if path.startswith(site):
                    raise forms.ValidationError(
                        'Paths for [%s] should be relative, not full URLs '
                        'including the domain name' % site
                    )
                validators.URLValidator()(path)
            else:
                path = ('/' if not path.startswith('/') else '') + path
                resolve(path)
        except forms.ValidationError as validation_error:
            # Re-raise the ValidationError about full paths for SITE_URL.
            raise validation_error
        except Exception as exc:
            raise forms.ValidationError('Path [%s] is not valid' % path) from exc
        return path


class ReplacementAddonAdmin(AMOModelAdmin):
    list_display = ('guid', 'path', 'guid_slug', '_url')
    form = ReplacementAddonForm

    def _url(self, obj):
        guid_param = urlencode({'guid': obj.guid})
        return format_html(
            '<a href="{}">Test</a>',
            reverse('addons.find_replacement') + '?%s' % guid_param,
        )

    def guid_slug(self, obj):
        try:
            slug = models.Addon.objects.get(guid=obj.guid).slug
        except models.Addon.DoesNotExist:
            slug = '- Add-on not on AMO -'
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
            return super().has_change_permission(request, obj=obj)
        else:
            return acl.action_allowed_for(
                request.user, amo.permissions.ADDONS_EDIT
            ) or super().has_change_permission(request, obj=obj)


@admin.register(models.AddonRegionalRestrictions)
class AddonRegionalRestrictionsAdmin(AMOModelAdmin):
    list_display = ('created', 'modified', 'addon__name', 'excluded_regions')
    fields = ('created', 'modified', 'addon', 'excluded_regions')
    raw_id_fields = ('addon',)
    readonly_fields = ('created', 'modified')
    view_on_site = False

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('addon',) if obj else ())

    def addon__name(self, obj):
        return str(obj.addon)

    addon__name.short_description = 'Addon'

    def _send_mail(self, obj, action):
        message = (
            f'Regional restriction for addon "{obj.addon.name}" '
            f'[{obj.addon.id}] {action}: {obj.excluded_regions}'
        )
        send_mail(
            f'Regional Restriction {action} for Add-on',
            message,
            recipient_list=('amo-notifications+regionrestrict@mozilla.com',),
        )

    def delete_model(self, request, obj):
        self._send_mail(obj, 'deleted')
        super().delete_model(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._send_mail(obj, 'changed' if change else 'added')


@admin.register(models.AddonBrowserMapping)
class AddonBrowserMappingAdmin(AMOModelAdmin):
    list_display = ('addon__name', 'browser', 'extension_id', 'created', 'modified')
    fields = ('addon', 'browser', 'extension_id')
    raw_id_fields = ('addon',)
    readonly_fields = ('created', 'modified')

    def addon__name(self, obj):
        return str(obj.addon)

    addon__name.short_description = 'Addon'


admin.site.register(models.DeniedGuid)
admin.site.register(models.Addon, AddonAdmin)
admin.site.register(models.FrozenAddon, FrozenAddonAdmin)
admin.site.register(models.ReplacementAddon, ReplacementAddonAdmin)
admin.site.register(models.AddonUser, AddonUserAdmin)
