from django.urls import include, re_path

from rest_framework.routers import SimpleRouter

from . import views


hero = SimpleRouter()
hero.register('primary', views.PrimaryHeroShelfViewSet, basename='hero-primary')
hero.register('secondary', views.SecondaryHeroShelfViewSet, basename='hero-secondary')

urlpatterns = [
    re_path(r'', include(hero.urls)),
    re_path(r'', views.HeroShelvesView.as_view(), name='hero-shelves'),
]
