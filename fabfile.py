from fabric.api import local


def pylint():
    local("cd ..;export DJANGO_SETTINGS_MODULE=zamboni/settings_local;"
        "PYTHONPATH=zamboni/apps:zamboni/lib "
        "pylint --rcfile zamboni/scripts/pylintrc zamboni ",
        capture=False)


def pep8(all=False):
    local("git fetch jbalogh")
    cmd = ("pep8 --repeat --ignore E221"
           " --exclude *.sh,*.html,*.json,*.txt,*.pyc,.DS_Store,README,"
           "migrations,sphinxapi.py")

    if all:
        cmd = cmd + " apps lib"
    else:
        cmd = cmd + " $(git diff --name-only jbalogh/master|grep py$)"
    local(cmd, capture=False)


def test(module=None, pdb=False, failfast=True):
    cmd = "python manage.py test"
    if module:
        cmd += " %s" % module

    if failfast and failfast != '0':
        cmd += " -x"

    cmd += " --noinput --logging-clear-handlers"
    if pdb:
        cmd += ' --pdb --pdb-failures -s'

    local(cmd, capture=False)
