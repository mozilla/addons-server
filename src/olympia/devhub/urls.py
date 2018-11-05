from django.conf.urls import include, url
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import partial
from olympia.lib.misc.urlconf_decorator import decorate

from . import views


# These will all start with /theme/<slug>/
theme_detail_patterns = [
    url(r'^$', lambda r,
        addon_id: redirect('devhub.themes.edit', addon_id, permanent=True)),
    url(r'^delete$', views.delete, name='devhub.themes.delete'),
    # Upload url here to satisfy CSRF.
    url(r'^edit/upload/'
        '(?P<upload_type>persona_header)$',
        views.ajax_upload_image, name='devhub.personas.reupload_persona'),
    url(r'^edit$', views.edit_theme, name='devhub.themes.edit'),
    url(r'^rmlocale$', views.remove_locale,
        name='devhub.themes.remove-locale'),
]

# These will all start with /addon/<addon_id>/
detail_patterns = [
    # Redirect to the edit page from the base.
    url(r'^$', lambda r, addon_id: redirect('devhub.addons.edit', addon_id,
                                            permanent=True)),
    url(r'^edit$', views.edit, name='devhub.addons.edit'),
    url(r'^delete$', views.delete, name='devhub.addons.delete'),
    url(r'^disable$', views.disable, name='devhub.addons.disable'),
    url(r'^enable$', views.enable, name='devhub.addons.enable'),
    url(r'^cancel$', views.cancel, name='devhub.addons.cancel'),
    url(r'^ownership$', views.ownership, name='devhub.addons.owner'),
    url(r'^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.addons.section'),

    url(r'^upload_preview$', views.upload_image, {'upload_type': 'preview'},
        name='devhub.addons.upload_preview'),
    url(r'^upload_icon$', views.upload_image, {'upload_type': 'icon'},
        name='devhub.addons.upload_icon'),

    url(r'^upload-(?P<channel>listed|unlisted)$', views.upload_for_version,
        name='devhub.upload_for_version'),
    url(r'^upload/(?P<uuid>[^/]+)$', views.upload_detail_for_version,
        name='devhub.upload_detail_for_version'),

    url(r'^versions$', views.version_list, name='devhub.addons.versions'),
    url(r'^versions/delete$', views.version_delete,
        name='devhub.versions.delete'),
    url(r'^versions/reenable$', views.version_reenable,
        name='devhub.versions.reenable'),
    url(r'^versions/stats$', views.version_stats,
        name='devhub.versions.stats'),
    url(r'^versions/(?P<version_id>\d+)$', views.version_edit,
        name='devhub.versions.edit'),
    url(r'^versions/(?P<version>[^/]+)$', views.version_bounce),

    # New version submission
    url(r'^versions/submit/$',
        views.submit_version_auto,
        name='devhub.submit.version'),
    url(r'^versions/submit/agreement$',
        views.submit_version_agreement,
        name='devhub.submit.version.agreement'),
    url(r'^versions/submit/distribution$',
        views.submit_version_distribution,
        name='devhub.submit.version.distribution'),
    url(r'^versions/submit/upload-(?P<channel>listed|unlisted)$',
        views.submit_version_upload,
        name='devhub.submit.version.upload'),
    url(r'^versions/submit/(?P<version_id>\d+)/source$',
        views.submit_version_source,
        name='devhub.submit.version.source'),
    url(r'^versions/submit/(?P<version_id>\d+)/details$',
        views.submit_version_details,
        name='devhub.submit.version.details'),
    url(r'^versions/submit/(?P<version_id>\d+)/finish$',
        views.submit_version_finish,
        name='devhub.submit.version.finish'),

    url(r'^versions/submit/wizard-(?P<channel>listed|unlisted)$',
        views.submit_version_theme_wizard,
        name='devhub.submit.version.wizard'),
    url('^versions/submit/wizard-(?P<channel>listed|unlisted)/background$',
        views.theme_background_image,
        name='devhub.submit.version.previous_background'),

    url(r'^file/(?P<file_id>[^/]+)/validation$', views.file_validation,
        name='devhub.file_validation'),
    url(r'^file/(?P<file_id>[^/]+)/validation\.json$',
        views.json_file_validation,
        name='devhub.json_file_validation'),

    url(r'^submit/$',
        lambda r, addon_id: redirect('devhub.submit.finish', addon_id)),
    url(r'^submit/source$',
        views.submit_addon_source, name='devhub.submit.source'),
    url(r'^submit/details$',
        views.submit_addon_details, name='devhub.submit.details'),
    url(r'^submit/finish$', views.submit_addon_finish,
        name='devhub.submit.finish'),

    url(r'^request-review$',
        views.request_review, name='devhub.request-review'),
    url(r'^rmlocale$', views.remove_locale,
        name='devhub.addons.remove-locale'),
]
# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = [
    url(r'^dependencies$', views.ajax_dependencies,
        name='devhub.ajax.dependencies'),
    url(r'^versions/compatibility/status$',
        views.ajax_compat_status, name='devhub.ajax.compat.status'),
    url(r'^versions/compatibility/error$',
        views.ajax_compat_error, name='devhub.ajax.compat.error'),
    url(r'^versions/(?P<version_id>\d+)/compatibility$',
        views.ajax_compat_update, name='devhub.ajax.compat.update'),
    url(r'^image/status$', views.image_status,
        name='devhub.ajax.image.status'),
]
redirect_patterns = [
    url(r'^addon/edit/(\d+)',
        lambda r, id: redirect('devhub.addons.edit', id, permanent=True)),
    url(r'^addon/status/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
    url(r'^versions/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
]

urlpatterns = decorate(use_primary_db, [
    url(r'^$', views.index, name='devhub.index'),
    url(r'', include(redirect_patterns)),

    # Redirect people who have /addons/ instead of /addon/.
    url(r'^addons/\d+/.*',
        lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Add-on submission
    url(r'^addon/submit/(?:1)?$',
        lambda r: redirect('devhub.submit.agreement', permanent=True)),
    url(r'^addon/submit/agreement$', views.submit_addon,
        name='devhub.submit.agreement'),
    url(r'^addon/submit/distribution$', views.submit_addon_distribution,
        name='devhub.submit.distribution'),
    url(r'^addon/submit/upload-(?P<channel>listed|unlisted)$',
        views.submit_addon_upload, name='devhub.submit.upload'),
    url(r'^addon/submit/wizard-(?P<channel>listed|unlisted)$',
        views.submit_addon_theme_wizard, name='devhub.submit.wizard'),

    # Submission API
    url(r'^addon/agreement/$', views.api_key_agreement,
        name='devhub.api_key_agreement'),

    url(r'^addon/api/key/$', views.api_key, name='devhub.api_key'),

    # Standalone validator:
    url(r'^addon/validate/?$', views.validate_addon,
        name='devhub.validate_addon'),

    # Redirect to /addons/ at the base.
    url(r'^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url(r'^addons$', views.dashboard, name='devhub.addons'),
    url(r'^themes$', views.dashboard, name='devhub.themes',
        kwargs={'theme': True}),
    url(r'^feed$', views.feed, name='devhub.feed_all'),
    # TODO: not necessary when devhub homepage is moved out of remora
    url(r'^feed/all$', lambda r: redirect('devhub.feed_all', permanent=True)),
    url(r'^feed/%s$' % ADDON_ID, views.feed, name='devhub.feed'),

    url(r'^upload$', views.upload, name='devhub.upload'),
    url(r'^upload/unlisted$',
        partial(views.upload, channel='unlisted'),
        name='devhub.upload_unlisted'),

    url(r'^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='devhub.upload_detail'),

    url(r'^standalone-upload$',
        partial(views.upload, is_standalone=True),
        name='devhub.standalone_upload'),
    url(r'^standalone-upload-unlisted$',
        partial(views.upload, is_standalone=True, channel='unlisted'),
        name='devhub.standalone_upload_unlisted'),
    url(r'^standalone-upload/([^/]+)$', views.standalone_upload_detail,
        name='devhub.standalone_upload_detail'),

    # URLs for a single add-on.
    url(r'^addon/%s/' % ADDON_ID, include(detail_patterns)),

    url(r'^ajax/addon/%s/' % ADDON_ID, include(ajax_patterns)),

    # Themes submission.
    url(r'^theme/submit/?$', views.submit_theme, name='devhub.themes.submit'),
    url(r'^theme/%s/submit/done$' % ADDON_ID, views.submit_theme_done,
        name='devhub.themes.submit.done'),
    url(r'^theme/submit/upload/'
        '(?P<upload_type>persona_header)$',
        views.ajax_upload_image, name='devhub.personas.upload_persona'),
    url(r'^theme/%s/' % ADDON_ID, include(theme_detail_patterns)),

    # Add-on SDK page
    url(r'builder$', lambda r: redirect(views.MDN_BASE)),

    # Developer docs
    url(r'docs/(?P<doc_name>[-_\w]+(?:/[-_\w]+)?)?$',
        views.docs, name='devhub.docs'),
])
