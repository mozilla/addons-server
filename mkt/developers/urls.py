from django.conf.urls.defaults import patterns, url, include
from django.shortcuts import redirect

from lib.misc.urlconf_decorator import decorate

from addons.urls import ADDON_ID
from amo.decorators import write
from mkt.developers.decorators import use_apps
from mkt.webapps.urls import APP_SLUG
from . import views


def paypal_patterns(prefix):
    return patterns('',
        url('^$', views.paypal_setup,
            name='mkt.developers.%s.paypal_setup' % prefix),
        url('^confirm$', views.paypal_setup_confirm,
            name='mkt.developers.%s.paypal_setup_confirm' % prefix,
            kwargs={'source': 'paypal'}),
        url('^details$', views.paypal_setup_confirm,
            name='mkt.developers.%s.paypal_setup_details' % prefix,
            kwargs={'source': 'developers'}),
        url('^bounce$', views.paypal_setup_bounce,
            name='mkt.developers.%s.paypal_setup_bounce' % prefix),
        url('^check$', views.paypal_setup_check,
            name='mkt.developers.%s.paypal_setup_check' % prefix),
    )


# These will all start with /app/<app_slug>/
app_detail_patterns = patterns('',
    url('^edit$', views.edit, name='mkt.developers.apps.edit'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='mkt.developers.apps.section'),
    url('^ownership$', views.ownership, name='mkt.developers.apps.owner'),
    url('^enable$', views.enable, name='mkt.developers.apps.enable'),
    url('^delete$', views.delete, name='mkt.developers.apps.delete'),
    url('^disable$', views.disable, name='mkt.developers.apps.disable'),
    url('^status$', views.status, name='mkt.developers.apps.versions'),

    url('^payments$', views.payments, name='mkt.developers.apps.payments'),
    # PayPal-specific stuff.
    url('^paypal/', include(paypal_patterns('apps'))),
    url('^paypal/', include(paypal_patterns('addons'))),

    # PayPal in-app stuff.
    url('^in-app-config$', views.in_app_config,
        name='mkt.developers.apps.in_app_config'),
    url('^in-app-secret$', views.in_app_secret,
        name='mkt.developers.apps.in_app_secret'),
    # Response from paypal.
    url('^payments/disable$', views.disable_payments,
        name='mkt.developers.apps.payments.disable'),
    url('^payments/permission/refund$', views.acquire_refund_permission,
        name='mkt.developers.apps.acquire_refund_permission'),
    # Old stuff.

    url('^upload_preview$', views.upload_image, {'upload_type': 'preview'},
        name='mkt.developers.apps.upload_preview'),
    url('^upload_icon$', views.upload_image, {'upload_type': 'icon'},
        name='mkt.developers.apps.upload_icon'),

    url('^profile$', views.profile, name='mkt.developers.apps.profile'),
    url('^profile/remove$', views.remove_profile,
        name='mkt.developers.apps.profile.remove'),
    url('^issue_refund$', views.issue_refund,
        name='mkt.developers.apps.issue_refund'),
    url('^refunds$', views.refunds, name='mkt.developers.apps.refunds'),
    url('^rmlocale$', views.remove_locale,
        name='mkt.developers.apps.remove-locale'),
)

# These will all start with /addon/<addon_id>/
detail_patterns = patterns('',
    # Redirect to the edit page from the base.
    url('^$', lambda r, addon_id: redirect('mkt.developers.addons.edit',
                                           addon_id, permanent=True)),
    url('^edit$', views.edit, name='mkt.developers.addons.edit'),
    url('^delete$', views.delete, name='mkt.developers.addons.delete'),
    url('^disable$', views.disable, name='mkt.developers.addons.disable'),
    url('^enable$', views.enable, name='mkt.developers.addons.enable'),
    url('^cancel$', views.cancel, name='mkt.developers.addons.cancel'),
    url('^ownership$', views.ownership, name='mkt.developers.addons.owner'),
    url('^payments$', views.payments, name='mkt.developers.addons.payments'),
    url('^payments/disable$', views.disable_payments,
        name='mkt.developers.addons.payments.disable'),
    url('^payments/permission/refund$', views.acquire_refund_permission,
        name='mkt.developers.addons.acquire_refund_permission'),
    url('^issue_refund$', views.issue_refund,
        name='mkt.developers.addons.issue_refund'),
    url('^refunds$', views.refunds, name='mkt.developers.addons.refunds'),
    url('^profile$', views.profile, name='mkt.developers.addons.profile'),
    url('^profile/remove$', views.remove_profile,
        name='mkt.developers.addons.profile.remove'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='mkt.developers.addons.section'),

    url('^upload_preview$', views.upload_image, {'upload_type': 'preview'},
        name='mkt.developers.addons.upload_preview'),
    url('^upload_icon$', views.upload_image, {'upload_type': 'icon'},
        name='mkt.developers.addons.upload_icon'),
    url('^upload$', views.upload_for_addon,
        name='mkt.developers.upload_for_addon'),
    url('^upload/(?P<uuid>[^/]+)$', views.upload_detail_for_addon,
        name='mkt.developers.upload_detail_for_addon'),

    url('^file/(?P<file_id>[^/]+)/validation$', views.file_validation,
        name='mkt.developers.file_validation'),
    url('^file/(?P<file_id>[^/]+)/validation.json$',
        views.json_file_validation,
        name='mkt.developers.json_file_validation'),

    url('^rmlocale$', views.remove_locale,
        name='mkt.developers.addons.remove-locale'),
)

# These will all start with /ajax/addon/<addon_id>/
ajax_patterns = patterns('',
    url('^image/status$', views.image_status,
        name='mkt.developers.ajax.image.status'),
)

urlpatterns = decorate(write, patterns('',
    url('^$', views.index, name='mkt.developers.index'),

    # Redirect people who have /addons/ instead of /addon/.
    ('^addons/\d+/.*',
     lambda r: redirect(r.path.replace('addons', 'addon', 1))),

    # Standalone validator:
    url('^addon/validate/?$', views.validate_addon,
        name='mkt.developers.validate_addon'),

    # Redirect to /addons/ at the base.
    url('^addon$',
        lambda r: redirect('mkt.developers.addons', permanent=True)),
    url('^addons$', views.dashboard, name='mkt.developers.addons'),
    url('^submissions$', use_apps(views.dashboard),
        name='mkt.developers.apps'),
    url('^upload$', views.upload, name='mkt.developers.upload'),
    url('^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='mkt.developers.upload_detail'),
    url('^standalone-upload$', views.standalone_upload,
        name='mkt.developers.standalone_upload'),
    url('^standalone-upload/([^/]+)$', views.standalone_upload_detail,
        name='mkt.developers.standalone_upload_detail'),

    url('^upload-manifest$', views.upload_manifest,
        name='mkt.developers.upload_manifest'),

    # URLs for a single add-on.
    url('^addon/%s/' % ADDON_ID, include(detail_patterns)),
    url('^app/%s/' % APP_SLUG, include(app_detail_patterns)),

    url('^ajax/addon/%s/' % ADDON_ID, include(ajax_patterns)),

    # Developer docs
    url('docs/(?P<doc_name>[-_\w]+)?$',
        views.docs, name='mkt.developers.docs'),
    url('docs/(?P<doc_name>[-_\w]+)/(?P<doc_page>[-_\w]+)',
        views.docs, name='mkt.developers.docs'),
))
