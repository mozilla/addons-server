import os
import sys

# Tell manage that we need to pull in the mkt settings file.
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings_local_mkt'

# Fix the path so we can import utils, then remove it.
sys.path.append(os.path.dirname(__file__))

from utils import application

del sys.path[sys.path.index(os.path.dirname(__file__))]
# vim: ft=python
