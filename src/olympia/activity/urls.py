from django.conf.urls import url

from . import views


urlpatterns = [url(r'^mail/', views.inbound_email, name='inbound-email-api')]
