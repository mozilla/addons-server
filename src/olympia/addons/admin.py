import functools
from urllib.parse import urlencode, urljoin

from django import http, forms
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.core import validators
from django.forms.models import modelformset_factory
from django.http.response import (
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404
from django.urls import resolve
from django.utils.encoding import force_text
from django.utils.html import format_html, format_html_join
from django.utils.translation import ugettext, ugettext_lazy as _

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, AddonUser
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.files.models import File
from olympia.git.models import GitExtractionEntry
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
                obj.user.email,
            )
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
        'created',
        'version__version',
        'version__channel',
        'platform',
        'status',
        'version__is_blocked',
        'hash_link',
    )
    editable_fields = ('status',)
    readonly_fields = tuple(set(fields) - set(editable_fields))
    can_delete = False
    view_on_site = False
    template = 'admin/addons/file_inline.html'
    checks_class = FileInlineChecks

    def version__version(self, obj):
        return obj.version.version + (' - Deleted' if obj.version.deleted else '')

    version__version.short_description = 'Version'

    def version__channel(self, obj):
        return obj.version.get_channel_display()

    version__channel.short_description = 'Channel'

    def version__is_blocked(self, obj):
        block = self.instance.block
        if not (block and block.is_version_blocked(obj.version.version)):
            return ''
        url = block.get_admin_url_path()
        template = '<a href="{}">Blocked ({} - {})</a>'
        return format_html(template, url, block.min_version, block.max_version)

    version__is_blocked.short_description = 'Block status'

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
        return qs.select_related('version')


class AddonAdmin(admin.ModelAdmin):
    class Media:
        css = {
            'all': (
                'css/admin/l10n.css',
                'css/admin/pagination.css',
                'css/admin/addons.css',
            )
        }
        js = ('admin/js/jquery.init.js', 'js/admin/l10n.js', 'js/admin/recalc_hash.js')

    list_display = (
        '__str__',
        'type',
        'guid',
        'status',
        'average_rating',
        'authors_links',
        'reviewer_links',
    )
    list_filter = ('type', 'status')
    search_fields = ('id', '^guid', '^slug')
    inlines = (AddonUserInline, FileInline)
    readonly_fields = (
        'id',
        'created',
        'average_rating',
        'bayesian_rating',
        'guid',
        'total_ratings_link',
        'text_ratings_count',
        'weekly_downloads',
        'average_daily_users',
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
    actions = ['git_extract_action']

    def get_queryset(self, request):
        # We want to _unlisted_versions_exists/_listed_versions_exists to avoid
        # repeating that query for each add-on in the list. A cleaner way to do this
        # would be to use annotate like this:
        # sub_qs = Version.unfiltered.filter(addon=OuterRef('pk')).values_list('id')
        # (...).annotate(
        #     _unlisted_versions_exists=Exists(
        #         sub_qs.filter(channel=amo.RELEASE_CHANNEL_UNLISTED)
        #     ),
        #     _listed_versions_exists=Exists(
        #         sub_qs.filter(channel=amo.RELEASE_CHANNEL_LISTED)
        #     ),
        # )
        # But while this works, the subquery is a lot less optimized (it does a full
        # query instead of the SELECT 1 ... LIMIT 1) and to make things worse django
        # admin doesn't know it's only for displayed data (it doesn't realize we aren't
        # filtering on it, and even if it did can't remove the annotations from the
        # queryset anyway) so it uses it for the count() queries as well, making them a
        # lot slower.
        subquery = (
            'SELECT 1 FROM `versions` WHERE `channel` = %s'
            ' AND `addon_id` = `addons`.`id` LIMIT 1'
        )
        extra = {
            'select': {
                '_unlisted_versions_exists': subquery,
                '_listed_versions_exists': subquery,
            },
            'select_params': (
                amo.RELEASE_CHANNEL_UNLISTED,
                amo.RELEASE_CHANNEL_LISTED,
            ),
        }
        return (
            Addon.unfiltered.all()
            .only_translations()
            .transform(Addon.attach_all_authors)
            .extra(**extra)
        )

    def get_urls(self):
        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return functools.update_wrapper(wrapper, view)

        urlpatterns = super(AddonAdmin, self).get_urls()
        custom_urlpatterns = [
            url(
                r'^(?P<object_id>.+)/git_extract/$',
                wrap(self.git_extract_view),
                name='addons_git_extract',
            ),
        ]
        return custom_urlpatterns + urlpatterns

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

    authors_links.short_description = _('Authors')

    def total_ratings_link(self, obj):
        return related_content_link(
            obj,
            Rating,
            'addon',
            related_manager='without_replies',
            text=obj.total_ratings,
        )

    total_ratings_link.short_description = _('Ratings')

    def reviewer_links(self, obj):
        links = []
        # _has_listed_versions_exists and _has_unlisted_versions_exists are
        # provided by annotations made in get_queryset()
        if obj._listed_versions_exists:
            links.append(
                '<a href="{}">{}</a>'.format(
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['listed', obj.id]),
                    ),
                    _('Reviewer Tools (listed)'),
                )
            )
        if obj._unlisted_versions_exists:
            links.append(
                '<a href="{}">{}</a>'.format(
                    urljoin(
                        settings.EXTERNAL_SITE_URL,
                        reverse('reviewers.review', args=['unlisted', obj.id]),
                    ),
                    _('Reviewer Tools (unlisted)'),
                )
            )
        return format_html('&nbsp;|&nbsp;'.join(links))

    reviewer_links.short_description = _('Reviewer links')

    def change_view(self, request, object_id, form_url='', extra_context=None):
        lookup_field = Addon.get_lookup_field(object_id)
        if lookup_field != 'pk':
            addon = None
            try:
                if lookup_field in ('slug', 'guid'):
                    addon = self.get_queryset(request).get(**{lookup_field: object_id})
            except Addon.DoesNotExist:
                raise http.Http404
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
            ActivityLog.create(amo.LOG.CHANGE_STATUS, obj, form.cleaned_data['status'])
            log.info(
                'Addon "%s" status changed to: %s'
                % (obj.slug, form.cleaned_data['status'])
            )

    def git_extract_action(self, request, qs):
        addon_ids = []
        for addon in qs:
            GitExtractionEntry.objects.create(addon=addon)
            addon_ids.append(force_text(addon))
        kw = {'addons': ', '.join(addon_ids)}
        self.message_user(
            request, ugettext('Git extraction triggered for "%(addons)s".' % kw)
        )

    git_extract_action.short_description = 'Git-Extract'

    def git_extract_view(self, request, object_id, extra_context=None):
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        if not acl.action_allowed(request, amo.permissions.ADDONS_EDIT):
            return HttpResponseForbidden()

        obj = get_object_or_404(Addon, id=object_id)

        self.git_extract_action(request, (obj,))

        return HttpResponseRedirect(
            reverse('admin:addons_addon_change', args=(obj.pk,))
        )


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
                        'including the domain name' % site
                    )
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
            reverse('addons.find_replacement') + '?%s' % guid_param,
        )

    def guid_slug(self, obj):
        try:
            slug = models.Addon.objects.get(guid=obj.guid).slug
        except models.Addon.DoesNotExist:
            slug = ugettext('- Add-on not on AMO -')
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
                request, obj=obj
            )
        else:
            return acl.action_allowed(request, amo.permissions.ADDONS_EDIT) or super(
                ReplacementAddonAdmin, self
            ).has_change_permission(request, obj=obj)


@admin.register(models.AddonRegionalRestrictions)
class AddonRegionalRestrictionsAdmin(admin.ModelAdmin):
    list_display = ('addon__name', 'excluded_regions')
    fields = ('created', 'modified', 'addon', 'excluded_regions')
    raw_id_fields = ('addon',)
    readonly_fields = ('created', 'modified')

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
            recipient_list=('amo-admins@mozilla.com',),
        )

    def delete_model(self, request, obj):
        self._send_mail(obj, 'deleted')
        super().delete_model(request, obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._send_mail(obj, 'changed' if change else 'added')


admin.site.register(models.DeniedGuid)
admin.site.register(models.Addon, AddonAdmin)
admin.site.register(models.FrozenAddon, FrozenAddonAdmin)
admin.site.register(models.ReplacementAddon, ReplacementAddonAdmin)
