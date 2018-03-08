from django.conf.urls import include, url
from django.shortcuts import redirect

from olympia.addons.urls import ADDON_ID
from olympia.amo.decorators import write
from olympia.amo.utils import partial
from olympia.lib.misc.urlconf_decorator import decorate

from . import views


# These will all start with /theme/<slug>/
theme_detail_patterns = [
    url('^$', lambda r,
        addon_id: redirect('devhub.themes.edit', addon_id, permanent=True)),
    url('^delete$', views.delete, name='devhub.themes.delete'),
    # Upload url here to satisfy CSRF.
    url('^edit/upload/'
        '(?P<upload_type>persona_header)$',
        views.ajax_upload_image, name='devhub.personas.reupload_persona'),
    url('^edit$', views.edit_theme, name='devhub.themes.edit'),
    url('^rmlocale$', views.remove_locale, name='devhub.themes.remove-locale'),
]

# These will all start with /addon/<addon_id>/
detail_patterns = [
    # Redirect to the edit page from the base.
    url('^$', lambda r, addon_id: redirect('devhub.addons.edit', addon_id,
                                           permanent=True)),
    url('^edit$', views.edit, name='devhub.addons.edit'),
    url('^delete$', views.delete, name='devhub.addons.delete'),
    url('^disable$', views.disable, name='devhub.addons.disable'),
    url('^enable$', views.enable, name='devhub.addons.enable'),
    url('^cancel$', views.cancel, name='devhub.addons.cancel'),
    url('^ownership$', views.ownership, name='devhub.addons.owner'),
    url('^admin$', views.admin, name='devhub.addons.admin'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.addons.section'),

    url('^upload_preview$', views.upload_image, {'upload_type': 'preview'},
        name='devhub.addons.upload_preview'),
    url('^upload_icon$', views.upload_image, {'upload_type': 'icon'},
        name='devhub.addons.upload_icon'),

    url('^upload-(?P<channel>listed|unlisted)$', views.upload_for_version,
        name='devhub.upload_for_version'),
    url('^upload/(?P<uuid>[^/]+)$', views.upload_detail_for_version,
        name='devhub.upload_detail_for_version'),

    url('^versions$', views.version_list, name='devhub.addons.versions'),
    url('^versions/delete$', views.version_delete,
        name='devhub.versions.delete'),
    url('^versions/reenable$', views.version_reenable,
        name='devhub.versions.reenable'),
    url('^versions/stats$', views.version_stats,
        name='devhub.versions.stats'),
    url('^versions/(?P<version_id>\d+)$', views.version_edit,
        name='devhub.versions.edit'),
    url('^versions/(?P<version>[^/]+)$', views.version_bounce),

    # New version submission
    url('^versions/submit/$',
        views.submit_version_auto,
        name='devhub.submit.version'),
    url('^versions/submit/agreement$',
        views.submit_version_agreement,
        name='devhub.submit.version.agreement'),
    url('^versions/submit/distribution$',
        views.submit_version_distribution,
        name='devhub.submit.version.distribution'),
    url('^versions/submit/upload-(?P<channel>listed|unlisted)$',
        views.submit_version_upload,
        name='devhub.submit.version.upload'),
    url('^versions/submit/(?P<version_id>\d+)/details$',
        views.submit_version_details,
        name='devhub.submit.version.details'),
    url('^versions/submit/(?P<version_id>\d+)/finish$',
        views.submit_version_finish,
        name='devhub.submit.version.finish'),

    url('^versions/submit/wizard-(?P<channel>listed|unlisted)$',
        views.submit_version_theme_wizard,
        name='devhub.submit.version.wizard'),

    # New file submission
    url('^versions/(?P<version_id>\d+)/submit-file/$',
        views.submit_file,
        name='devhub.submit.file'),
    url('^versions/submit/(?P<version_id>\d+)/finish-file$',
        views.submit_file_finish,
        name='devhub.submit.file.finish'),

    url('^file/(?P<file_id>[^/]+)/validation$', views.file_validation,
        name='devhub.file_validation'),
    url('^file/(?P<file_id>[^/]+)/validation\.json$',
        views.json_file_validation,
        name='devhub.json_file_validation'),

    url('^validation-result/(?P<result_id>\d+)$',
        views.bulk_compat_result,
        name='devhub.bulk_compat_result'),
    url('^validation-result/(?P<result_id>\d+)\.json$',
        views.json_bulk_compat_result,
        name='devhub.json_bulk_compat_result'),

    url('^submit/$',
        lambda r, addon_id: redirect('devhub.submit.finish', addon_id)),
    url('^submit/details$',
        views.submit_addon_details, name='devhub.submit.details'),
    url('^submit/finish$', views.submit_addon_finish,
        name='devhub.submit.finish'),

    url('^request-review$',
        views.request_review, name='devhub.request-review'),
    url('^rmlocale$', views.remove_locale, name='devhub.addons.remove-locale'),
]
# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = [
    url('^dependencies$', views.ajax_dependencies,
        name='devhub.ajax.dependencies'),
    url('^versions/compatibility/status$',
        views.ajax_compat_status, name='devhub.ajax.compat.status'),
    url('^versions/compatibility/error$',
        views.ajax_compat_error, name='devhub.ajax.compat.error'),
    url('^versions/(?P<version_id>\d+)/compatibility$',
        views.ajax_compat_update, name='devhub.ajax.compat.update'),
    url('^image/status$', views.image_status, name='devhub.ajax.image.status'),
]
redirect_patterns = [
    url('^addon/edit/(\d+)',
        lambda r, id: redirect('devhub.addons.edit', id, permanent=True)),
    url('^addon/status/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
    url('^versions/(\d+)',
        lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
]

urlpatterns = decorate(write, [
    url('^$', views.index, name='devhub.index'),
    url('', include(redirect_patterns)),

    # Redirect people who have /addons/ instead of /addon/.
    url('^addons/\d+/.*',
        lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Add-on submission
    url('^addon/submit/(?:1)?$',
        lambda r: redirect('devhub.submit.agreement', permanent=True)),
    url('^addon/submit/agreement$', views.submit_addon,
        name='devhub.submit.agreement'),
    url('^addon/submit/distribution$', views.submit_addon_distribution,
        name='devhub.submit.distribution'),
    url('^addon/submit/upload-(?P<channel>listed|unlisted)$',
        views.submit_addon_upload, name='devhub.submit.upload'),
    url('^addon/submit/wizard-(?P<channel>listed|unlisted)$',
        views.submit_addon_theme_wizard, name='devhub.submit.wizard'),

    # Submission API
    url('^addon/agreement/$', views.api_key_agreement,
        name='devhub.api_key_agreement'),

    url('^addon/api/key/$', views.api_key, name='devhub.api_key'),

    # Standalone validator:
    url('^addon/validate/?$', views.validate_addon,
        name='devhub.validate_addon'),

    # Standalone compatibility checker:
    url('^addon/check-compatibility$', views.check_addon_compatibility,
        name='devhub.check_addon_compatibility'),
    url(r'^addon/check-compatibility/application_versions\.json$',
        views.compat_application_versions,
        name='devhub.compat_application_versions'),

    # Redirect to /addons/ at the base.
    url('^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url('^addons$', views.dashboard, name='devhub.addons'),
    url('^themes$', views.dashboard, name='devhub.themes',
        kwargs={'theme': True}),
    url('^feed$', views.feed, name='devhub.feed_all'),
    # TODO: not necessary when devhub homepage is moved out of remora
    url('^feed/all$', lambda r: redirect('devhub.feed_all', permanent=True)),
    url('^feed/%s$' % ADDON_ID, views.feed, name='devhub.feed'),

    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/unlisted$',
        partial(views.upload, channel='unlisted'),
        name='devhub.upload_unlisted'),

    url('^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='devhub.upload_detail'),

    url('^standalone-upload$',
        partial(views.upload, is_standalone=True),
        name='devhub.standalone_upload'),
    url('^standalone-upload-unlisted$',
        partial(views.upload, is_standalone=True, channel='unlisted'),
        name='devhub.standalone_upload_unlisted'),
    url('^standalone-upload/([^/]+)$', views.standalone_upload_detail,
        name='devhub.standalone_upload_detail'),

    # URLs for a single add-on.
    url('^addon/%s/' % ADDON_ID, include(detail_patterns)),

    url('^ajax/addon/%s/' % ADDON_ID, include(ajax_patterns)),

    # Themes submission.
    url('^theme/submit/?$', views.submit_theme, name='devhub.themes.submit'),
    url('^theme/%s/submit/done$' % ADDON_ID, views.submit_theme_done,
        name='devhub.themes.submit.done'),
    url('^theme/submit/upload/'
        '(?P<upload_type>persona_header)$',
        views.ajax_upload_image, name='devhub.personas.upload_persona'),
    url('^theme/%s/' % ADDON_ID, include(theme_detail_patterns)),

    # Add-on SDK page
    url('builder$', lambda r: redirect(views.MDN_BASE)),

    # Developer docs
    url('docs/(?P<doc_name>[-_\w]+(?:/[-_\w]+)?)?$',
        views.docs, name='devhub.docs'),
])
