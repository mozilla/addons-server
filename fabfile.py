from fabric.api import local

def pep8():
    local("pep8.py --repeat --ignore E221"
    " --exclude *.sh,*.html,*.json,*.txt,*.pyc,.DS_Store,README"
    " apps")
