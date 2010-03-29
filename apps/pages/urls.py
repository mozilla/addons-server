from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    url('^about$', views.about_amo, name='pages.about'),
    url('^faq$', views.faq, name='pages.faq'),
)
