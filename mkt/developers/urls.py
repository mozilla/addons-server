from django import http
from django.conf.urls import include, patterns, url

from rest_framework.routers import SimpleRouter

from lib.misc.urlconf_decorator import decorate

import amo
from amo.decorators import write
from mkt.api.base import AppRouter
from mkt.developers.api import ContentRatingList, ContentRatingsPingback
from mkt.developers.api_payments import (
    AddonPaymentAccountViewSet, PaymentAccountViewSet, PaymentCheckViewSet,
    PaymentDebugViewSet, PaymentViewSet, UpsellViewSet)
from mkt.developers.decorators import use_apps
from mkt.receipts.urls import test_patterns
from mkt.stats.urls import all_apps_stats_patterns

from . import views
from . import views_payments


def provider_patterns(prefix):
    return patterns('',
        url('^accounts$', views_payments.payment_accounts,
            name='mkt.developers.%s.payment_accounts' % prefix),

        url('^accounts/form$', views_payments.payment_accounts_form,
            name='mkt.developers.%s.payment_accounts_form' % prefix),

        url('^accounts/add$', views_payments.payments_accounts_add,
            name='mkt.developers.%s.add_payment_account' % prefix),

        url('^accounts/(?P<id>\d+)/delete$',
            views_payments.payments_accounts_delete,
            name='mkt.developers.%s.delete_payment_account' % prefix),

        url('^accounts/(?P<id>\d+)$',
            views_payments.payments_account,
            name='mkt.developers.%s.payment_account' % prefix),

        url('^accounts/(?P<id>\d+)/agreement/$', views_payments.agreement,
            name='mkt.developers.%s.agreement' % prefix)
    )


# These will all start with /app/<app_slug>/
app_detail_patterns = patterns('',
    url('^edit$', views.edit, name='mkt.developers.apps.edit'),
    url('^edit_(?P<section>[^/]+)(?:/(?P<editable>[^/]+))?$',
        views.addons_section, name='mkt.developers.apps.section'),
    url('^refresh_manifest$', views.refresh_manifest,
        name='mkt.developers.apps.refresh_manifest'),
    url('^ownership$', views.ownership, name='mkt.developers.apps.owner'),
    url('^enable$', views.enable, name='mkt.developers.apps.enable'),
    url('^delete$', views.delete, name='mkt.developers.apps.delete'),
    url('^disable$', views.disable, name='mkt.developers.apps.disable'),
    url('^publicise$', views.publicise, name='mkt.developers.apps.publicise'),
    url('^status$', views.status, name='mkt.developers.apps.versions'),
    url('^blocklist$', views.blocklist, name='mkt.developers.apps.blocklist'),

    # IARC content ratings.
    url('^content_ratings$', views.content_ratings,
        name='mkt.developers.apps.ratings'),
    url('^content_ratings/edit$', views.content_ratings_edit,
        name='mkt.developers.apps.ratings_edit'),

    url('^status/preload$', views.preload_home,
        name='mkt.developers.apps.preload_home'),
    url('^status/preload/submit$', views.preload_submit,
        name='mkt.developers.apps.preload_submit'),

    # TODO: '^versions/$'
    url('^versions/(?P<version_id>\d+)$', views.version_edit,
        name='mkt.developers.apps.versions.edit'),
    url('^versions/delete$', views.version_delete,
        name='mkt.developers.apps.versions.delete'),
    url('^versions/publicise$', views.version_publicise,
        name='mkt.developers.apps.versions.publicise'),

    url('^payments/$', views_payments.payments,
        name='mkt.developers.apps.payments'),
    url('^payments/disable$', views_payments.disable_payments,
        name='mkt.developers.apps.payments.disable'),
    url('^payments/bango-portal$', views_payments.bango_portal_from_addon,
        name='mkt.developers.apps.payments.bango_portal_from_addon'),
    # in-app payments.
    url('^in-app-config/$', views_payments.in_app_config,
        name='mkt.developers.apps.in_app_config'),
    url('^in-app-secret/$', views_payments.in_app_secret,
        name='mkt.developers.apps.in_app_secret'),
    # Old stuff.

    url('^upload_preview$', views.upload_media, {'upload_type': 'preview'},
        name='mkt.developers.apps.upload_preview'),
    url('^upload_icon$', views.upload_media, {'upload_type': 'icon'},
        name='mkt.developers.apps.upload_icon'),
    url('^upload_image$', views.upload_media, {'upload_type': 'image'},
        name='mkt.developers.apps.upload_image'),

    url('^rmlocale$', views.remove_locale,
        name='mkt.developers.apps.remove-locale'),

    # Not apps-specific (yet).
    url('^file/(?P<file_id>[^/]+)/validation$', views.file_validation,
        name='mkt.developers.apps.file_validation'),
    url('^file/(?P<file_id>[^/]+)/validation.json$',
        views.json_file_validation,
        name='mkt.developers.apps.json_file_validation'),
    url('^upload$', views.upload_for_addon,
        name='mkt.developers.upload_for_addon'),
    url('^upload/(?P<uuid>[^/]+)$', views.upload_detail_for_addon,
        name='mkt.developers.upload_detail_for_addon'),
)

# These will all start with /ajax/app/<app_slug>/
ajax_patterns = patterns('',
    url('^image/status$', views.image_status,
        name='mkt.developers.apps.ajax.image.status'),
)

urlpatterns = decorate(write, patterns('',
    # Redirect people who have /apps/ instead of /app/.
    ('^apps/\d+/.*',
     lambda r: http.HttpResponseRedirect(r.path.replace('apps', 'app', 1))),

    # Standalone validator:
    url('^validator/?$', views.validate_addon,
        name='mkt.developers.validate_addon'),

    # Redirect to /addons/ at the base.
    url('^submissions$', use_apps(views.dashboard),
        name='mkt.developers.apps'),
    url('^upload$', views.upload_new, name='mkt.developers.upload'),
    url('^upload/([^/]+)(?:/([^/]+))?$', views.upload_detail,
        name='mkt.developers.upload_detail'),
    url('^standalone-hosted-upload$', views.standalone_hosted_upload,
        name='mkt.developers.standalone_hosted_upload'),
    url('^standalone-packaged-upload$', views.standalone_packaged_upload,
        name='mkt.developers.standalone_packaged_upload'),
    url('^standalone-(hosted|packaged)-upload/([^/]+)$',
        views.standalone_upload_detail,
        name='mkt.developers.standalone_upload_detail'),

    # Standalone tools.
    url('^upload-manifest$', views.upload_manifest,
        name='mkt.developers.upload_manifest'),
    url('^in-app-keys/$', views_payments.in_app_keys,
        name='mkt.developers.apps.in_app_keys'),
    url('^in-app-key-secret/([^/]+)$', views_payments.in_app_key_secret,
        name='mkt.developers.apps.in_app_key_secret'),

    # URLs for a single app.
    url('^app/%s/' % amo.APP_SLUG, include(app_detail_patterns)),
    url('^ajax/app/%s/' % amo.APP_SLUG, include(ajax_patterns)),

    url('^terms$', views.terms, name='mkt.developers.apps.terms'),
    url('^api$', views.api, name='mkt.developers.apps.api'),

    # Developer docs
    url('docs/(?P<doc_name>[-_\w]+)?$',
        views.docs, name='mkt.developers.docs'),
    url('docs/(?P<doc_name>[-_\w]+)/(?P<doc_page>[-_\w]+)',
        views.docs, name='mkt.developers.docs'),

    url('^statistics/', include(all_apps_stats_patterns)),
    url('^transactions/', views.transactions,
        name='mkt.developers.transactions'),

    # Bango-specific stuff.
    url('^bango/', include(provider_patterns('bango'))),
    url('^reference/', include(provider_patterns('reference'))),

    url('^test/$', views.testing, name='mkt.developers.apps.testing'),
    url('^test/receipts/', include(test_patterns)),
))

api_payments = SimpleRouter()
api_payments.register(r'account', PaymentAccountViewSet,
                      base_name='payment-account')
api_payments.register(r'upsell', UpsellViewSet, base_name='app-upsell')
api_payments.register(r'app', AddonPaymentAccountViewSet,
                      base_name='app-payment-account')

app_payments = AppRouter()
app_payments.register(r'payments', PaymentViewSet, base_name='app-payments')
app_payments.register(r'payments/status', PaymentCheckViewSet,
                      base_name='app-payments-status')
app_payments.register(r'payments/debug', PaymentDebugViewSet,
                      base_name='app-payments-debug')

payments_api_patterns = patterns('',
    url(r'^payments/', include(api_payments.urls)),
    url(r'^apps/app/', include(app_payments.urls)),
)

dev_api_patterns = patterns('',
    url(r'^apps/app/(?P<pk>[^/<>"\']+)/content-ratings/pingback/',
        ContentRatingsPingback.as_view(), name='content-ratings-pingback'),
    url(r'^apps/app/(?P<pk>[^/<>"\']+)/content-ratings/',
        ContentRatingList.as_view(), name='content-ratings-list'),
)
