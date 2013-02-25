# This script builds assets in Jenkins to make sure there are no
# less compilation errors

cd $WORKSPACE
VENV=$WORKSPACE/venv
VENDOR=$WORKSPACE/vendor

echo "Starting build on executor $EXECUTOR_NUMBER..." `date`

if [ -z $1 ]; then
    echo "Usage: $0 django_settings_module"
    exit 1
fi

SETTINGS=$1

# Delete old artifacts.
find . -name '*.pyc' -or -name '*less.css' -or -name '*-min.css'-or -name '*-all.css' -or -name '*-min.js' -or -name '*-all.js' -delete

if [ ! -d "$VENV/bin" ]; then
    echo "No virtualenv found.  Making one..."
    virtualenv $VENV --system-site-packages
fi

source $VENV/bin/activate

pip install -U --exists-action=w --no-deps -q -r requirements/compiled.txt -r requirements/test.txt

if [ ! -d "$VENDOR" ]; then
    echo "No vendor lib?  Cloning..."
    git clone --recursive git://github.com/mozilla/zamboni-lib.git $VENDOR
fi

# Install node deps locally.
npm install
export PATH="./node_modules/.bin/:${PATH}"

cat > settings_local.py <<SETTINGS
from ${SETTINGS} import *
UGLIFY_BIN = 'uglifyjs'
SETTINGS

export DJANGO_SETTINGS_MODULE=settings_local

# Update the vendor lib.
echo "Updating vendor..."
git submodule --quiet foreach 'git submodule --quiet sync'
git submodule --quiet sync && git submodule update --init --recursive

echo "building assets..." `date`

python manage.py compress_assets
exit $?
