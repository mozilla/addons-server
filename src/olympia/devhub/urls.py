from django.urls import include, re_path
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import partial
from olympia.lib.misc.urlconf_decorator import decorate

from . import views


# These will all start with /addon/<addon_id>/
detail_patterns = [
    # Redirect to the edit page from the base.
    re_path(
        r'^$',
        lambda r, addon_id: redirect('devhub.addons.edit', addon_id, permanent=True),
    ),
    re_path(r'^edit$', views.edit, name='devhub.addons.edit'),
    re_path(r'^delete$', views.delete, name='devhub.addons.delete'),
    re_path(r'^disable$', views.disable, name='devhub.addons.disable'),
    re_path(r'^enable$', views.enable, name='devhub.addons.enable'),
    re_path(r'^cancel$', views.cancel, name='devhub.addons.cancel'),
    re_path(r'^ownership$', views.ownership, name='devhub.addons.owner'),
    re_path(r'^invitation$', views.invitation, name='devhub.addons.invitation'),
    re_path(
        r'^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section,
        name='devhub.addons.section',
    ),
    re_path(
        r'^onboarding-subscription$',
        views.onboarding_subscription,
        name='devhub.addons.onboarding_subscription',
    ),
    re_path(
        r'^onboarding-subscription/success$',
        views.onboarding_subscription_success,
        name='devhub.addons.onboarding_subscription_success',
    ),
    re_path(
        r'^onboarding-subscription/cancel$',
        views.onboarding_subscription_cancel,
        name='devhub.addons.onboarding_subscription_cancel',
    ),
    re_path(
        r'^subscription/customer-portal$',
        views.subscription_customer_portal,
        name='devhub.addons.subscription_customer_portal',
    ),
    re_path(
        r'^upload_preview$',
        views.upload_image,
        {'upload_type': 'preview'},
        name='devhub.addons.upload_preview',
    ),
    re_path(
        r'^upload_icon$',
        views.upload_image,
        {'upload_type': 'icon'},
        name='devhub.addons.upload_icon',
    ),
    re_path(
        r'^upload-(?P<channel>listed|unlisted)$',
        views.upload_for_version,
        name='devhub.upload_for_version',
    ),
    re_path(
        r'^upload/(?P<uuid>[^/]+)$',
        views.upload_detail_for_version,
        name='devhub.upload_detail_for_version',
    ),
    re_path(r'^versions$', views.version_list, name='devhub.addons.versions'),
    re_path(r'^versions/delete$', views.version_delete, name='devhub.versions.delete'),
    re_path(
        r'^versions/reenable$', views.version_reenable, name='devhub.versions.reenable'
    ),
    re_path(r'^versions/stats$', views.version_stats, name='devhub.versions.stats'),
    re_path(
        r'^versions/(?P<version_id>\d+)$',
        views.version_edit,
        name='devhub.versions.edit',
    ),
    re_path(r'^versions/(?P<version>[^/]+)$', views.version_bounce),
    # New version submission
    re_path(
        r'^versions/submit/$', views.submit_version_auto, name='devhub.submit.version'
    ),
    re_path(
        r'^versions/submit/agreement$',
        views.submit_version_agreement,
        name='devhub.submit.version.agreement',
    ),
    re_path(
        r'^versions/submit/distribution$',
        views.submit_version_distribution,
        name='devhub.submit.version.distribution',
    ),
    re_path(
        r'^versions/submit/upload-(?P<channel>listed|unlisted)$',
        views.submit_version_upload,
        name='devhub.submit.version.upload',
    ),
    re_path(
        r'^versions/submit/(?P<version_id>\d+)/source$',
        views.submit_version_source,
        name='devhub.submit.version.source',
    ),
    re_path(
        r'^versions/submit/(?P<version_id>\d+)/details$',
        views.submit_version_details,
        name='devhub.submit.version.details',
    ),
    re_path(
        r'^versions/submit/(?P<version_id>\d+)/finish$',
        views.submit_version_finish,
        name='devhub.submit.version.finish',
    ),
    re_path(
        r'^versions/submit/wizard-(?P<channel>listed|unlisted)$',
        views.submit_version_theme_wizard,
        name='devhub.submit.version.wizard',
    ),
    re_path(
        '^versions/submit/wizard-(?P<channel>listed|unlisted)/background$',
        views.theme_background_image,
        name='devhub.submit.version.previous_background',
    ),
    re_path(
        r'^file/(?P<file_id>[^/]+)/validation$',
        views.file_validation,
        name='devhub.file_validation',
    ),
    re_path(
        r'^file/(?P<file_id>[^/]+)/validation\.json$',
        views.json_file_validation,
        name='devhub.json_file_validation',
    ),
    re_path(
        r'^submit/$', lambda r, addon_id: redirect('devhub.submit.finish', addon_id)
    ),
    re_path(r'^submit/source$', views.submit_addon_source, name='devhub.submit.source'),
    re_path(
        r'^submit/details$', views.submit_addon_details, name='devhub.submit.details'
    ),
    re_path(r'^submit/finish$', views.submit_addon_finish, name='devhub.submit.finish'),
    re_path(r'^request-review$', views.request_review, name='devhub.request-review'),
    re_path(r'^rmlocale$', views.remove_locale, name='devhub.addons.remove-locale'),
]
# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = [
    re_path(
        r'^versions/compatibility/status$',
        views.ajax_compat_status,
        name='devhub.ajax.compat.status',
    ),
    re_path(
        r'^versions/compatibility/error$',
        views.ajax_compat_error,
        name='devhub.ajax.compat.error',
    ),
    re_path(
        r'^versions/(?P<version_id>\d+)/compatibility$',
        views.ajax_compat_update,
        name='devhub.ajax.compat.update',
    ),
    re_path(r'^image/status$', views.image_status, name='devhub.ajax.image.status'),
]
redirect_patterns = [
    re_path(
        r'^addon/edit/(\d+)',
        lambda r, id: redirect('devhub.addons.edit', id, permanent=True),
    ),
    re_path(
        r'^addon/status/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True),
    ),
    re_path(
        r'^versions/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True),
    ),
]

urlpatterns = decorate(
    use_primary_db,
    [
        re_path(r'^$', views.index, name='devhub.index'),
        re_path(r'', include(redirect_patterns)),
        # Redirect people who have /addons/ instead of /addon/.
        re_path(
            r'^addons/\d+/.*', lambda r: redirect(r.path.replace('addons', 'addon', 1))
        ),
        # Add-on submission
        re_path(
            r'^addon/submit/(?:1)?$',
            lambda r: redirect('devhub.submit.agreement', permanent=True),
        ),
        re_path(
            r'^addon/submit/agreement$',
            views.submit_addon,
            name='devhub.submit.agreement',
        ),
        re_path(
            r'^addon/submit/distribution$',
            views.submit_addon_distribution,
            name='devhub.submit.distribution',
        ),
        re_path(
            r'^addon/submit/upload-(?P<channel>listed|unlisted)$',
            views.submit_addon_upload,
            name='devhub.submit.upload',
        ),
        re_path(
            r'^addon/submit/wizard-(?P<channel>listed|unlisted)$',
            views.submit_addon_theme_wizard,
            name='devhub.submit.wizard',
        ),
        # Submission API
        re_path(
            r'^addon/agreement/$',
            views.api_key_agreement,
            name='devhub.api_key_agreement',
        ),
        re_path(r'^addon/api/key/$', views.api_key, name='devhub.api_key'),
        # Standalone validator:
        re_path(
            r'^addon/validate/?$', views.validate_addon, name='devhub.validate_addon'
        ),
        # Redirect to /addons/ at the base.
        re_path(r'^addon$', lambda r: redirect('devhub.addons', permanent=True)),
        re_path(r'^addons$', views.dashboard, name='devhub.addons'),
        re_path(
            r'^themes$', views.dashboard, name='devhub.themes', kwargs={'theme': True}
        ),
        re_path(r'^feed$', views.feed, name='devhub.feed_all'),
        # TODO: not necessary when devhub homepage is moved out of remora
        re_path(r'^feed/all$', lambda r: redirect('devhub.feed_all', permanent=True)),
        re_path(r'^feed/%s$' % ADDON_ID, views.feed, name='devhub.feed'),
        re_path(r'^upload$', views.upload, name='devhub.upload'),
        re_path(
            r'^upload/unlisted$',
            partial(views.upload, channel='unlisted'),
            name='devhub.upload_unlisted',
        ),
        re_path(
            r'^upload/([^/]+)(?:/([^/]+))?$',
            views.upload_detail,
            name='devhub.upload_detail',
        ),
        re_path(
            r'^standalone-upload$',
            partial(views.upload, is_standalone=True),
            name='devhub.standalone_upload',
        ),
        re_path(
            r'^standalone-upload-unlisted$',
            partial(views.upload, is_standalone=True, channel='unlisted'),
            name='devhub.standalone_upload_unlisted',
        ),
        re_path(
            r'^standalone-upload/([^/]+)$',
            views.standalone_upload_detail,
            name='devhub.standalone_upload_detail',
        ),
        # URLs for a single add-on.
        re_path(r'^addon/%s/' % ADDON_ID, include(detail_patterns)),
        re_path(r'^ajax/addon/%s/' % ADDON_ID, include(ajax_patterns)),
        # Old LWT Theme submission.
        re_path(
            r'^theme/submit/?$',
            lambda r: redirect('devhub.submit.agreement'),
            name='devhub.themes.submit',
        ),
        # Add-on SDK page
        re_path(r'builder$', lambda r: redirect(views.MDN_BASE)),
        # Developer docs
        re_path(
            r'docs/(?P<doc_name>[-_\w]+(?:/[-_\w]+)?)?$', views.docs, name='devhub.docs'
        ),
        # logout page
        re_path(r'^logout', views.logout, name='devhub.logout'),
    ],
)
