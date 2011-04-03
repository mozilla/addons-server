# This script should be called from within Hudson


cd $WORKSPACE
VENV=$WORKSPACE/venv
VENDOR=$WORKSPACE/vendor
LOCALE=$WORKSPACE/locale
LOG=$WORKSPACE/jstests-runserver.log

echo "Starting build on executor $EXECUTOR_NUMBER..." `date`

if [ -z $1 ]; then
    echo "Warning: You should provide a unique name for this job to prevent database collisions."
    echo "Usage: $0 <name>"
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

pip install -q -r requirements/compiled.txt

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
    git clone --recursive git://github.com/jbalogh/zamboni-lib.git $VENDOR
fi

# Update the vendor lib.
echo "Updating vendor..."
pushd $VENDOR && git pull && git submodule --quiet sync && git submodule update --init;
popd

cat > settings_local.py <<SETTINGS
from settings import *
ROOT_URLCONF = '%s.urls' % ROOT_PACKAGE
LOG_LEVEL = logging.ERROR
# Database name has to be set because of sphinx
DATABASES['default']['NAME'] = 'zamboni_$1'
DATABASES['default']['HOST'] = 'localhost'
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

# Activate Qunit:
INSTALLED_APPS += (
    'django_qunit',
)

SETTINGS


# All DB tables need to exist so that runserver can start up.
python manage.py syncdb --noinput

echo "Starting JS tests..." `date`

rm $LOG
# NOTE: the host value here needs to match the 'zambnoi' suite in jstestnet
cd scripts
python run_jstests.py -v --with-xunit --with-zamboni --zamboni-host sm-hudson01 --zamboni-log $LOG --with-jstests --jstests-server http://jstestnet.farmdev.com/ --jstests-suite zamboni --jstests-browsers firefox --debug nose.plugins.jstests

echo 'shazam!'
