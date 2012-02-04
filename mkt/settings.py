from lib.settings_base import *

APP_PREVIEW = True
ROOT_URLCONF = 'mkt.urls'
TEMPLATE_DIRS = (path('mkt/templates'),) + TEMPLATE_DIRS
POTCH_MARKETPLACE_EXPERIMENTS = False
INSTALLED_APPS = INSTALLED_APPS + ('mkt.experiments',)
