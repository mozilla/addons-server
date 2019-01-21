from django.conf import settings
from django.conf.urls import url
from django.http import HttpResponsePermanentRedirect as perma_redirect
from django.views.generic.base import TemplateView

from olympia.amo.urlresolvers import reverse


urlpatterns = [
    url(r'^about$',
        TemplateView.as_view(template_name='pages/about.lhtml'),
        name='pages.about'),
    url(r'^google1f3e37b7351799a5\.html$',
        TemplateView.as_view(
            template_name='pages/google_webmaster_verification.html')),
    url(r'^google231a41e803e464e9\.html$',
        TemplateView.as_view(
            template_name='pages/google_search_console.html')),
    url(r'^review_guide$',
        TemplateView.as_view(template_name='pages/review_guide.html'),
        name='pages.review_guide'),

    url(r'^shield-study-2/',
        lambda req: perma_redirect(settings.SHIELD_STUDIES_SUPPORT_URL)),
    url(r'^shield_study_\d{1,2}$',
        lambda req: perma_redirect(settings.SHIELD_STUDIES_SUPPORT_URL)),

    url(r'^pages/review_guide$',
        lambda req: perma_redirect(reverse('pages.review_guide'))),
    url(r'^pages/developer_agreement$',
        lambda req: perma_redirect(reverse('devhub.docs',
                                           args=['policies/agreement']))),
    url(r'^pages/validation$',
        lambda req: perma_redirect(settings.VALIDATION_FAQ_URL)),

    url(r'^pioneer$',
        TemplateView.as_view(template_name='pages/pioneer.html'),
        name='pages.pioneer'),
]
