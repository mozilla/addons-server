from django.conf.urls import include, patterns, url

from . import views

# These will all start with /localizers/<locale_code>/
detail_patterns = patterns('',
    url('^$', views.locale_dashboard, name='localizers.locale_dashboard'),
    url('^categories/$', views.categories, name='localizers.categories'),
)

urlpatterns = patterns('',
    ('^(?P<locale_code>[\w-]+)/', include(detail_patterns)),

    url('^$', views.summary, name='localizers.dashboard'),
    url('^set_motd$', views.set_motd, name='localizers.set_motd'),
)
