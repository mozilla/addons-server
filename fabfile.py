import os
from os.path import join as pjoin

from fabric.api import (env, execute, lcd, local, parallel,
                        run, roles, task)

import fabdeploytools.envs
from fabdeploytools import helpers

import deploysettings as settings

os.environ['DJANGO_SETTINGS_MODULE'] = 'settings_local'

env.key_filename = settings.SSH_KEY
fabdeploytools.envs.loadenv(settings.CLUSTER)

ROOT, OLYMPIA = helpers.get_app_dirs(__file__)

VIRTUALENV = pjoin(ROOT, 'venv')
PYTHON = pjoin(VIRTUALENV, 'bin', 'python')


def managecmd(cmd, run_dir=OLYMPIA):
    with lcd(run_dir):
        local('../venv/bin/python manage.py %s' % cmd)


@task
def create_virtualenv(update_on_change=False):
    helpers.create_venv(VIRTUALENV, settings.PYREPO,
                        pjoin(OLYMPIA, 'requirements/prod.txt'),
                        update_on_change=update_on_change)

    if settings.LOAD_TESTING:
        helpers.pip_install_reqs(pjoin(OLYMPIA, 'requirements/load.txt'))


@task
def update_locales():
    with lcd(pjoin(OLYMPIA, 'locale')):
        local("VENV=%s ./compile-mo.sh ." % VIRTUALENV)


@task
def loadtest(repo=''):
    if hasattr(settings, 'MARTEAU'):
        os.environ['MACAUTH_USER'] = settings.MARTEAU_USER
        os.environ['MACAUTH_SECRET'] = settings.MARTEAU_SECRET
        local('%s %s --server %s' % (settings.MARTEAU, repo,
                                     settings.MARTEAU_SERVER))


@task
def update_products():
    managecmd('update_product_details')


@task
def compress_assets(arg=''):
    managecmd('compress_assets -t %s' % arg)


@task
def collectstatic():
    managecmd('collectstatic --noinput')


@task
def schematic(run_dir=OLYMPIA):
    with lcd(run_dir):
        local('../venv/bin/python ../venv/bin/schematic migrations')


@task
def update_info(ref='origin/master'):
    helpers.git_info(OLYMPIA)
    with lcd(OLYMPIA):
        local("/bin/bash -c "
              "'source /etc/bash_completion.d/git && __git_ps1'")
        local('git show -s {0} --pretty="format:%h" '
              '> media/git-rev.txt'.format(ref))


@task
def disable_cron():
    local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron(installed_dir):
    installed_olympia_dir = os.path.join(installed_dir, 'olympia')
    installed_python = os.path.join(installed_dir, 'venv', 'bin', 'python')
    with lcd(OLYMPIA):
        local('%s ./scripts/crontab/gen-cron.py '
              '-z %s -u %s -p %s > /etc/cron.d/.%s' %
              (PYTHON, installed_olympia_dir,
               getattr(settings, 'CRON_USER', 'apache'),
               installed_python, settings.CRON_NAME))

        local('mv /etc/cron.d/.%s /etc/cron.d/%s' % (settings.CRON_NAME,
                                                     settings.CRON_NAME))


@task
@roles('celery')
@parallel
def update_celery():
    restarts = []
    if getattr(settings, 'CELERY_SERVICE_PREFIX', False):
        restarts.extend(['supervisorctl restart {0}{1} &'.format(
                         settings.CELERY_SERVICE_PREFIX, x)
                         for x in ('', '-devhub', '-priority', '-limited')])
    if restarts:
        run('%s wait' % ' '.join(restarts))


@task
def deploy():
    rpmbuild = helpers.deploy(name='olympia',
                              env=settings.ENV,
                              cluster=settings.CLUSTER,
                              domain=settings.DOMAIN,
                              root=ROOT,
                              deploy_roles=['web', 'celery'],
                              package_dirs=['olympia', 'venv'])

    helpers.restart_uwsgi(getattr(settings, 'UWSGI', []))
    execute(update_celery)
    execute(install_cron, rpmbuild.install_to)
    managecmd('cron cleanup_validation_results')


@task
def deploy_web():
    helpers.deploy(name='olympia',
                   env=settings.ENV,
                   cluster=settings.CLUSTER,
                   domain=settings.DOMAIN,
                   root=ROOT,
                   use_yum=False,
                   package_dirs=['olympia', 'venv'])

    helpers.restart_uwsgi(getattr(settings, 'UWSGI', []))


@task
def pre_update(ref=settings.UPDATE_REF):
    local('date')
    execute(disable_cron)
    execute(helpers.git_update, OLYMPIA, ref)
    execute(update_info, ref)


@task
def update():
    execute(create_virtualenv, getattr(settings, 'DEV', False))
    execute(update_locales)
    execute(update_products)
    execute(compress_assets)
    execute(collectstatic)
    execute(schematic)
    managecmd('statsd_ping --key=update')


@task
def build():
    execute(create_virtualenv, getattr(settings, 'DEV', False))
    execute(update_locales)
    execute(update_products)
    execute(compress_assets)
    execute(collectstatic)
    managecmd('statsd_ping --key=update')


@task
def deploy_jenkins():
    rpmbuild = helpers.build_rpm(name='olympia',
                                 env=settings.ENV,
                                 cluster=settings.CLUSTER,
                                 domain=settings.DOMAIN,
                                 root=ROOT,
                                 package_dirs=['olympia', 'venv'])

    rpmbuild.local_install()

    install_dir = os.path.join(rpmbuild.install_to, 'olympia')
    execute(schematic, install_dir)
    managecmd('dump_apps', install_dir)

    rpmbuild.remote_install(['web', 'celery'])
    helpers.restart_uwsgi(getattr(settings, 'UWSGI', []))

    execute(update_celery)
    execute(install_cron, rpmbuild.install_to)
    managecmd('cron cleanup_validation_results')


@task
def pre_update_latest_tag():
    current_tag_file = os.path.join(OLYMPIA, '.tag')
    latest_tag = helpers.git_latest_tag(OLYMPIA)
    with open(current_tag_file, 'r+') as f:
        if f.read() == latest_tag:
            print 'Environemnt is at %s' % latest_tag
        else:
            pre_update(latest_tag)
            f.seek(0)
            f.write(latest_tag)
            f.truncate()
