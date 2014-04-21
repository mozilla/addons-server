# This script should be called from within Hudson


cd $WORKSPACE
VENV=$WORKSPACE/venv
VENDOR=$WORKSPACE/vendor
LOCALE=$WORKSPACE/locale
ES_HOST='jenkins-es20'
SETTINGS=default

echo "Starting build on executor $EXECUTOR_NUMBER..." `date`

if [ -z $1 ]; then
    echo "Warning: You should provide a unique name for this job to prevent database collisions."
    echo "Usage: ./build.sh <name>"
    echo "Continuing, but don't say you weren't warned."
fi

if [ -z $2 ]; then
    echo "Warning: no settings file specified, using: default"
    echo "Usage: ./build.sh <name> <settings>"
else
    SETTINGS=$2
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

# Create paths we want for addons
if [ ! -d "/tmp/warez" ]; then
    mkdir /tmp/warez
fi

if [ ! -d "$LOCALE" ]; then
    echo "No locale dir?  Cloning..."
    svn co http://svn.mozilla.org/addons/trunk/site/app/locale/ $LOCALE
fi

if [ ! -d "$VENDOR" ]; then
    echo "No vendor lib?  Cloning..."
    git clone --recursive git://github.com/mozilla/zamboni-lib.git $VENDOR
fi

# Update the vendor lib.
echo "Updating vendor..."
git submodule --quiet foreach 'git submodule --quiet sync'
git submodule --quiet sync && git submodule update --init --recursive

if [ -z $SET_ES_TESTS ]; then
    RUN_ES_TESTS=False
else
    RUN_ES_TESTS=True
fi

cat > settings_local.py <<SETTINGS
from lib.settings_base import *
from ${SETTINGS}.settings import *
ROOT_URLCONF = 'lib.urls_base'
LOG_LEVEL = logging.ERROR
DATABASES['default']['NAME'] = 'zamboni_$1'
DATABASES['default']['HOST'] = 'localhost'
DATABASES['default']['USER'] = 'hudson'
DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
DATABASES['default']['TEST_NAME'] = 'test_zamboni_$1'
DATABASES['default']['TEST_CHARSET'] = 'utf8'
DATABASES['default']['TEST_COLLATION'] = 'utf8_general_ci'
CACHES = {
    'default': {
        'BACKEND': 'caching.backends.locmem.LocMemCache',
    }
}
CELERY_ALWAYS_EAGER = True
RUN_ES_TESTS = ${RUN_ES_TESTS}
ES_HOSTS = ['${ES_HOST}:9200']
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ADDONS_PATH = '/tmp/warez'
STATIC_URL = ''

SETTINGS

# Update product details to pull in any changes (namely, 'dbg' locale)
echo "Updating product details..."
python manage.py update_product_details


echo "Starting tests..." `date`
export FORCE_DB='yes sir'

if [[ $3 = 'with-coverage' ]]; then
    coverage run manage.py test -v 2 --noinput --logging-clear-handlers --with-xunit
    coverage xml $(find apps lib -name '*.py')
else
    python manage.py test -v 2 --noinput --logging-clear-handlers --with-xunit --with-blockage --http-whitelist=127.0.0.1,localhost,${ES_HOST} lib.es.tests.test_commands:TestIndexCommand.test_reindexation
fi


echo "Building documentation..." `date`
cd docs
make clean dirhtml SPHINXOPTS='-q'
cd $WORKSPACE

echo 'shazam!'
