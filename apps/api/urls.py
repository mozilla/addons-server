from django.conf.urls.defaults import patterns, url

from . import views


urlpatterns = patterns('',
    # Redirect api requests without versions
    url('^((?:addon)/.*)$', views.redirect_view),
    url('^(\d+|\d+\.\d+)/addon/(\d+)$',
        lambda *args, **kwargs: views.AddonDetailView()(*args, **kwargs),
        name='api.addon_detail'),

)
