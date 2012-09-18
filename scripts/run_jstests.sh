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
  virtualenv $VENV --system-site-packages
fi

source $VENV/bin/activate

pip install -U --exists-action=w --no-deps -q -r requirements/compiled.txt -r requirements/test.txt

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

cp -f docs/settings/settings_local.dev.py settings_local.py
cat >> settings_local.py <<SETTINGS

ROOT_URLCONF = 'lib.urls_base'
LOG_LEVEL = logging.ERROR

DATABASES = {
    'default': {
        'NAME': 'zamboni_$1',
        'HOST': 'localhost',
        'ENGINE': 'django.db.backends.mysql',
        'USER': 'hudson',
        'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
        'TEST_NAME': 'test_zamboni_$1',
        'TEST_CHARSET': 'utf8',
        'TEST_COLLATION': 'utf8_general_ci',
    },
}

CACHE_BACKEND = 'caching.backends.locmem://'
CELERY_ALWAYS_EAGER = True
ADDONS_PATH = '/tmp/warez'

# Activate Qunit:
INSTALLED_APPS += (
    'django_qunit',
)

SETTINGS


# All DB tables need to exist so that runserver can start up.
python manage.py syncdb --noinput

echo "Starting JS tests..." `date`

rm $LOG
cd scripts
# Some of these env vars are set in the Jenkins build step.
BROWSERS=firefox
XARGS="-v --with-xunit --with-django-serv --django-host $DJANGO_HOST --django-port $DJANGO_PORT --django-log $LOG --django-startup-uri /robots.txt --django-root-dir $WORKSPACE --with-jstests --jstests-server http://jstestnet.farmdev.com/ --jstests-suite zamboni --jstests-token $JSTESTS_TOKEN --jstests-browsers $BROWSERS --debug nose.plugins.jstests"
python run_jstests.py --jstests-url http://$DJANGO_HOST:$DJANGO_PORT/en-US/qunit/ --xunit-file=nosetests.xml $XARGS

echo 'shazam!'
