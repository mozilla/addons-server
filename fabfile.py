from fabric.api import local

def pep8():
    local("pep8 --repeat --ignore E221"
        " --exclude *.sh,*.html,*.json,*.txt,*.pyc,.DS_Store,README,"
        "migrations,sphinxapi.py"
        " apps", capture=False)


def test():
    local("python manage.py test --noinput --logging-clear-handlers",
          capture=False)
