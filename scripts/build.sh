# This script should be called from within Hudson

cd $WORKSPACE
VENV=$WORKSPACE/venv

echo "Starting build..."

# Make sure there's no old pyc files around.
find . -name '*.pyc' | xargs rm

if [ ! -d "$VENV/bin" ]; then
  echo "No virtualenv found.  Making one..."
  virtualenv --no-site-packages $VENV
fi

source $VENV/bin/activate

pip install -q -r requirements.txt

cat > settings_local.py <<SETTINGS
from settings import *
ROOT_URLCONF = 'workspace.urls'
SETTINGS

echo "Starting tests..."
coverage run manage.py test --noinput --logging-clear-handlers --with-xunit
coverage xml $(find apps lib -name '*.py')

echo "Building documentation..."
cd docs
make clean dirhtml SPHINXOPTS='-q'
cd $WORKSPACE

echo "Taking forever to make a bundle..."
PKG=$WORKSPACE/packages
rm -rf $PKG && mkdir $PKG && pip -q bundle -r requirements-prod.txt $PKG/amo.pybundle

echo 'shazam!'
