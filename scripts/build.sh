# This script should be called from within Hudson


cd $WORKSPACE
VENV=$WORKSPACE/venv

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
  virtualenv $VENV
fi

source $VENV/bin/activate

pip install -q -r requirements/dev.txt -r requirements/compiled.txt

# Create paths we want for addons
if [ ! -d "/tmp/warez" ]; then
    mkdir /tmp/warez
fi

cat > settings_local.py <<SETTINGS
from settings import *
ROOT_URLCONF = '%s.urls' % ROOT_PACKAGE
LOG_LEVEL = logging.ERROR
# Database name has to be set because of sphinx
DATABASES['default']['NAME'] = 'zamboni_$1'
DATABASES['default']['HOST'] = 'sm-hudson01'
DATABASES['default']['USER'] = 'hudson'
DATABASES['default']['TEST_NAME'] = 'test_zamboni_$1'
DATABASES['default']['TEST_CHARSET'] = 'utf8'
DATABASES['default']['TEST_COLLATION'] = 'utf8_general_ci'
CACHE_BACKEND = 'caching.backends.locmem://'
CELERY_ALWAYS_EAGER = True
ADDONS_PATH = '/tmp/warez'

TEST_SPHINX_CATALOG_PATH = TMP_PATH + '/$1/data/sphinx'
TEST_SPHINX_LOG_PATH = TMP_PATH + '/$1/log/serachd'
TEST_SPHINXQL_PORT = 340${EXECUTOR_NUMBER}
TEST_SPHINX_PORT = 341${EXECUTOR_NUMBER}

ASYNC_SIGNALS = False
SETTINGS


echo "Starting tests..." `date`
export FORCE_DB='yes sir'

# with-coverage excludes sphinx so it doesn't conflict with real builds.
if [[ $2 = 'with-coverage' ]]; then
    coverage run manage.py test --noinput --logging-clear-handlers --with-xunit -a'!sphinx'
    coverage xml $(find apps lib -name '*.py')
else
    python manage.py test --noinput --logging-clear-handlers --with-xunit
fi


echo "Building documentation..." `date`
cd docs
make clean dirhtml SPHINXOPTS='-q'
cd $WORKSPACE

echo 'shazam!'
