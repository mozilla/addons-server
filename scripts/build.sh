# This script should be called from within Hudson

if [ ! -z $SET_PY_27 ]; then
    source /opt/rh/python27/enable
fi

# Echo the python version used in this build.
python --version

cd $WORKSPACE
VENV=$WORKSPACE/venv
LOCALE=$WORKSPACE/locale
ES_HOST='elasticsearch-1.3'

echo "Starting build on executor $EXECUTOR_NUMBER..." `date`

if [ -z $1 ]; then
    echo "Warning: You should provide a unique name for this job to prevent database collisions."
    echo "Usage: ./build.sh <name>"
    echo "Continuing, but don't say you weren't warned."
fi

echo "Setup..." `date`

# Make sure there's no old pyc files around.
find . -name '*.pyc' | xargs rm

if [ ! -d "$VENV/bin" ]; then
  echo "No virtualenv found.  Making one..."
  virtualenv $VENV --system-site-packages
fi

source $VENV/bin/activate

pip install -U --exists-action=w --no-deps -q \
	--download-cache=$WORKSPACE/.pip-cache \
	-f https://pyrepo.addons.mozilla.org/ \
	-r requirements/compiled.txt -r requirements/test.txt

cat > local_settings.py <<SETTINGS
from settings_ci import *

DATABASES['default']['NAME'] = 'zamboni_$1'
DATABASES['default']['HOST'] = 'localhost'
DATABASES['default']['USER'] = 'hudson'
DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
DATABASES['default']['TEST_NAME'] = 'test_zamboni_$1'
DATABASES['default']['TEST_CHARSET'] = 'utf8'
DATABASES['default']['TEST_COLLATION'] = 'utf8_general_ci'
SERVICES_DATABASE['NAME'] = DATABASES['default']['NAME']
SERVICES_DATABASE['USER'] = DATABASES['default']['USER']
ES_HOSTS = ['${ES_HOST}:10200']
ES_URLS = ['http://%s' % h for h in ES_HOSTS]

RUNNING_IN_JENKINS = True

SETTINGS


echo "Starting tests..." `date`

py.test -v


echo "Building documentation..." `date`
cd docs
make clean dirhtml SPHINXOPTS='-q'
cd $WORKSPACE

echo 'shazam!'
