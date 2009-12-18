# This script should be called from within Hudson

echo "Starting build..."

if [ ! -d "$WORKSPACE/bin" ]; then
  echo "No virtualenv found.  Making one..."
  virtualenv --no-site-packages $WORKSPACE
fi

source bin/activate

pip install -r requirements.txt

cat > local_settings.py <<SETTINGS
from settings import *
ROOT_URLCONF = 'workspace.urls'
SETTINGS

echo "Starting tests..."
python manage.py test --noinput --with-coverage --with-xunit --with-xcoverage --cover-package=workspace

echo "Building documentation..."
cd docs
make dirhtml

echo "done"
