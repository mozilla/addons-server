from django.conf.urls import include, patterns, url
from django.shortcuts import redirect

from lib.misc.urlconf_decorator import decorate

from addons.urls import ADDON_ID
import amo
from amo.decorators import write
from devhub.decorators import use_apps
from . import views

PACKAGE_NAME = '(?P<package_name>[_\w]+)'


# These will all start with /addon/<addon_id>/submit/
submit_patterns = patterns('',
    url('^$', lambda r, addon_id: redirect('devhub.submit.7', addon_id)),
    url('^3$', views.submit_describe, name='devhub.submit.3'),
    url('^4$', views.submit_media, name='devhub.submit.4'),
    url('^5$', views.submit_license, name='devhub.submit.5'),
    url('^6$', views.submit_select_review, name='devhub.submit.6'),
    url('^7$', views.submit_done, name='devhub.submit.7'),
    url('^bump$', views.submit_bump, name='devhub.submit.bump'),
)

submit_apps_patterns = patterns('',
    url('^3$', use_apps(views.submit_describe), name='devhub.submit_apps.3'),
    url('^4$', use_apps(views.submit_media), name='devhub.submit_apps.4'),
    url('^5$', use_apps(views.submit_done), name='devhub.submit_apps.5'),
    url('^bump$', use_apps(views.submit_bump), name='devhub.submit_apps.bump'),
)


def marketplace_patterns(prefix):
    return patterns('',
        url('^1$', views.marketplace_paypal,
            name='devhub.%s.market.1' % prefix),
        url('^2$', views.marketplace_pricing,
            name='devhub.%s.market.2' % prefix),
        url('^3$', views.marketplace_upsell,
            name='devhub.%s.market.3' % prefix),
        url('^4$', views.marketplace_confirm,
            name='devhub.%s.market.4' % prefix),
    )

# These will all start with /theme/<theme_slug>/
theme_detail_patterns = patterns('',
    url('^$', lambda r,
        addon_id: redirect('devhub.themes.edit', addon_id,
                           permanent=True)),
    url('^edit$', views.edit, name='devhub.themes.edit'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.themes.section'),
)

# These will all start with /app/<app_slug>/
app_detail_patterns = patterns('',
    url('^edit$', views.edit, name='devhub.apps.edit'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.apps.section'),
    url('^ownership$', views.ownership, name='devhub.apps.owner'),
    url('^enable$', views.enable, name='devhub.apps.enable'),
    url('^delete$', views.delete, name='devhub.apps.delete'),
    url('^disable$', views.disable, name='devhub.apps.disable'),
    url('^status$', views.version_list, name='devhub.apps.versions'),
    url('^payments$', views.payments, name='devhub.apps.payments'),
    url('^payments/disable$', views.disable_payments,
        name='devhub.apps.payments.disable'),
    url('^payments/permission/refund$', views.acquire_refund_permission,
        name='devhub.apps.acquire_refund_permission'),
    url('^payments/', include(marketplace_patterns('apps'))),
    url('^profile$', views.profile, name='devhub.apps.profile'),
    url('^profile/remove$', views.remove_profile,
        name='devhub.apps.profile.remove'),
    url('^issue_refund$', views.issue_refund, name='devhub.apps.issue_refund'),
    url('^refunds$', views.refunds, name='devhub.apps.refunds'),
    url('^rmlocale$', views.remove_locale, name='devhub.apps.remove-locale'),
)

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
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
    url('^payments$', views.payments, name='devhub.addons.payments'),
    url('^payments/disable$', views.disable_payments,
        name='devhub.addons.payments.disable'),
    url('^payments/permission/refund$', views.acquire_refund_permission,
        name='devhub.addons.acquire_refund_permission'),
    url('^payments/', include(marketplace_patterns('addons'))),
    url('^issue_refund$', views.issue_refund,
        name='devhub.addons.issue_refund'),
    url('^refunds$', views.refunds, name='devhub.addons.refunds'),
    url('^profile$', views.profile, name='devhub.addons.profile'),
    url('^profile/remove$', views.remove_profile,
        name='devhub.addons.profile.remove'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='devhub.addons.section'),

    url('^upload_preview$', views.upload_image, {'upload_type': 'preview'},
        name='devhub.addons.upload_preview'),
    url('^upload_icon$', views.upload_image, {'upload_type': 'icon'},
        name='devhub.addons.upload_icon'),
    url('^upload$', views.upload_for_addon,
        name='devhub.upload_for_addon'),
    url('^upload/(?P<uuid>[^/]+)$', views.upload_detail_for_addon,
        name='devhub.upload_detail_for_addon'),

    url('^versions$', views.version_list, name='devhub.addons.versions'),
    url('^versions/delete$', views.version_delete,
        name='devhub.versions.delete'),
    url('^versions/add$', views.version_add, name='devhub.versions.add'),
    url('^versions/stats$', views.version_stats,
        name='devhub.versions.stats'),
    url('^versions/(?P<version_id>\d+)$', views.version_edit,
        name='devhub.versions.edit'),
    url('^versions/(?P<version_id>\d+)/add$', views.version_add_file,
        name='devhub.versions.add_file'),
    url('^versions/(?P<version>[^/]+)$', views.version_bounce),

    url('^file/(?P<file_id>[^/]+)/validation$', views.file_validation,
        name='devhub.file_validation'),
    url('^file/(?P<file_id>[^/]+)/validation.json$',
        views.json_file_validation,
        name='devhub.json_file_validation'),

    url('^validation-result/(?P<result_id>\d+)$',
        views.bulk_compat_result,
        name='devhub.bulk_compat_result'),
    url('^validation-result/(?P<result_id>\d+).json$',
        views.json_bulk_compat_result,
        name='devhub.json_bulk_compat_result'),

    url('^submit/', include(submit_patterns)),
    url('^submit/resume$', views.submit_resume, name='devhub.submit.resume'),
    url('^request-review/(?P<status>[%s])$'
        % ''.join(map(str, views.REQUEST_REVIEW)),
        views.request_review, name='devhub.request-review'),
    url('^rmlocale$', views.remove_locale, name='devhub.addons.remove-locale'),
)

# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = patterns('',
    url('^dependencies$', views.ajax_dependencies,
        name='devhub.ajax.dependencies'),
    url('^versions/compatibility/status$',
        views.ajax_compat_status, name='devhub.ajax.compat.status'),
    url('^versions/compatibility/error$',
        views.ajax_compat_error, name='devhub.ajax.compat.error'),
    url('^versions/(?P<version_id>\d+)/compatibility$',
        views.ajax_compat_update, name='devhub.ajax.compat.update'),
    url('^image/status$', views.image_status, name='devhub.ajax.image.status'),

    # Performance testing
    url(r'^performance/file/(?P<file_id>\d+)/start-tests.json$',
        views.file_perf_tests_start, name='devhub.file_perf_tests_start'),
)

packager_patterns = patterns('',
    url('^$', views.package_addon, name='devhub.package_addon'),
    url('^download/%s.zip$' % PACKAGE_NAME, views.package_addon_download,
        name='devhub.package_addon_download'),
    url('^json/%s$' % PACKAGE_NAME, views.package_addon_json,
        name='devhub.package_addon_json'),
    url('^success/%s$' % PACKAGE_NAME, views.package_addon_success,
        name='devhub.package_addon_success'),
)

redirect_patterns = patterns('',
    ('^addon/edit/(\d+)',
     lambda r, id: redirect('devhub.addons.edit', id, permanent=True)),
    ('^addon/status/(\d+)',
     lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
    ('^versions/(\d+)',
     lambda r, id: redirect('devhub.addons.versions', id, permanent=True)),
    ('^versions/validate/(\d+)', views.validator_redirect),
)


urlpatterns = decorate(write, patterns('',
    url('^$', views.index, name='devhub.index'),
    url('', include(redirect_patterns)),

    # Redirect people who have /addons/ instead of /addon/.
    ('^addons/\d+/.*',
     lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Add-on submission
    url('^addon/submit/$',
        lambda r: redirect('devhub.submit.1', permanent=True)),
    url('^addon/submit/1$', views.submit, name='devhub.submit.1'),
    url('^addon/submit/2$', views.submit_addon, name='devhub.submit.2'),

    # Web App submission
    url('^app/submit/$',
        lambda r: redirect('devhub.submit_apps.1', permanent=True)),
    url('^app/submit/1$', use_apps(views.submit),
        name='devhub.submit_apps.1'),
    url('^app/submit/2$', use_apps(views.submit_addon),
        name='devhub.submit_apps.2'),

    # Standalone validator:
    url('^addon/validate/?$', views.validate_addon,
        name='devhub.validate_addon'),

    # Standalone compatibility checker:
    url('^addon/check-compatibility$', views.check_addon_compatibility,
        name='devhub.check_addon_compatibility'),
    url(r'^addon/check-compatibility/application_versions\.json$',
        views.compat_application_versions,
        name='devhub.compat_application_versions'),

    # Add-on packager
    url('^tools/package/', include(packager_patterns)),

    # Redirect to /addons/ at the base.
    url('^addon$', lambda r: redirect('devhub.addons', permanent=True)),
    url('^addons$', views.dashboard, name='devhub.addons'),
    url('^apps$', use_apps(views.dashboard), name='devhub.apps'),
    url('^feed$', views.feed, name='devhub.feed_all'),
    # TODO: not necessary when devhub homepage is moved out of remora
    url('^feed/all$', lambda r: redirect('devhub.feed_all', permanent=True)),
    url('^feed/%s$' % ADDON_ID, views.feed, name='devhub.feed'),
    url('^upload$', views.upload, name='devhub.upload'),
    url('^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='devhub.upload_detail'),
    url('^standalone-upload$', views.standalone_upload,
        name='devhub.standalone_upload'),
    url('^standalone-upload/([^/]+)$', views.standalone_upload_detail,
        name='devhub.standalone_upload_detail'),

    url('^upload-manifest$', views.upload_manifest,
        name='devhub.upload_manifest'),

    # URLs for a single add-on.
    url('^addon/%s/' % ADDON_ID, include(detail_patterns)),
    url('^app/%s/' % amo.APP_SLUG, include(app_detail_patterns)),
    url('^app/%s/submit/' % ADDON_ID, include(submit_apps_patterns)),

    url('^ajax/addon/%s/' % ADDON_ID, include(ajax_patterns)),

    # Themes submission.
    url('^theme/submit/?$', views.submit_persona,
        name='devhub.personas.submit'),
    url('^theme/%s/submit/done$' % ADDON_ID, views.submit_persona_done,
        name='devhub.personas.submit.done'),
    url('^theme/submit/upload/'
        '(?P<upload_type>persona_header|persona_footer)$',
        views.ajax_upload_image, name='devhub.personas.upload_persona'),
    url('^theme/%s/' % ADDON_ID, include(theme_detail_patterns)),

    # Add-on SDK page
    url('builder$', views.builder, name='devhub.builder'),

    # Developer docs
    url('docs/(?P<doc_name>[-_\w]+)?$',
        views.docs, name='devhub.docs'),
    url('docs/(?P<doc_name>[-_\w]+)/(?P<doc_page>[-_\w]+)',
        views.docs, name='devhub.docs'),

    # PayPal Checker
    url('^check_paypal$', views.check_paypal, name='devhub.check_paypal'),

    # Search
    url(r'^search$', views.search, name='devhub.search'),
))
