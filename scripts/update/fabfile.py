import os
import time
from fabric.api import (env, execute, lcd, local, parallel,
                        run, roles, task)

from fabdeploytools.rpm import RPMBuild
from fabdeploytools import helpers

import commander.hosts
import commander_settings as settings


env.key_filename = settings.SSH_KEY
env.roledefs.update(commander.hosts.hostgroups)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                    '..', '..', '..'))
ZAMBONI = os.path.join(ROOT, 'zamboni')

VIRTUALENV = os.path.join(ROOT, 'venv')

BUILD_ID = str(int(time.time()))

KEEP_RELEASES = 4

DOMAIN = getattr(settings, 'DOMAIN', 'addons-dev.allizom.org')
ENV = getattr(settings, 'ENV', 'dev')
CLUSTER = getattr(settings, 'CLUSTER', settings.WEB_HOSTGROUP)


def get_version():
    with lcd(ZAMBONI):
        ref = local('git rev-parse HEAD', capture=True)
    return ref


def get_setting(n, default=None):
    return getattr(settings, n, default)


@task
def create_virtualenv():
    with lcd(ZAMBONI):
        status = local('git diff HEAD@{1} HEAD --name-only')

    if 'requirements/' in status:
        venv = VIRTUALENV
        if not venv.startswith('/data'):
            raise Exception('venv must start with /data')

        local('rm -rf %s' % venv)
        helpers.create_venv(venv, settings.PYREPO,
                            '%s/requirements/prod.txt' % ZAMBONI)

        if getattr(settings, 'LOAD_TESTING', False):
            local('%s/bin/pip install --exists-action=w --no-deps '
                  '--no-index --download-cache=/tmp/pip-cache -f %s '
                  '-r %s/requirements/load.txt' %
                  (venv, settings.PYREPO, ZAMBONI))


@task
def update_locales():
    with lcd(os.path.join(ZAMBONI, 'locale')):
        local("svn revert -R .")
        local("svn up")
        local("./compile-mo.sh .")


@task
def loadtest(repo=''):
    if hasattr(settings, 'MARTEAU'):
        os.environ['MACAUTH_USER'] = settings.MARTEAU_USER
        os.environ['MACAUTH_SECRET'] = settings.MARTEAU_SECRET
        local('%s %s --server %s' % (settings.MARTEAU, repo,
                                     settings.MARTEAU_SERVER))


@task
def update_products():
    with lcd(ZAMBONI):
        local('%s manage.py update_product_details' % settings.PYTHON)


@task
def compress_assets(arg=''):
    with lcd(ZAMBONI):
        local("%s manage.py compress_assets -t %s" % (settings.PYTHON,
                                                      arg))


@task
def schematic():
    with lcd(ZAMBONI):
        local("%s %s/bin/schematic migrations" %
              (settings.PYTHON, VIRTUALENV))


@task
def update_info(ref='origin/master'):
    helpers.git_info(ZAMBONI)
    with lcd(ZAMBONI):
        local("/bin/bash -c "
              "'source /etc/bash_completion.d/git && __git_ps1'")
        local('git show -s {0} --pretty="format:%h" '
              '> media/git-rev.txt'.format(ref))


@task
@roles(settings.WEB_HOSTGROUP, settings.CELERY_HOSTGROUP)
@parallel
def install_package(rpmbuild):
    rpmbuild.install_package()


@task
def disable_cron():
    local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron():
    with lcd(ZAMBONI):
        local('%s ./scripts/crontab/gen-cron.py '
              '-z %s -u apache -p %s > /etc/cron.d/.%s' %
              (settings.PYTHON, ZAMBONI,
               settings.PYTHON, settings.CRON_NAME))

        local('mv /etc/cron.d/.%s /etc/cron.d/%s' % (settings.CRON_NAME,
                                                     settings.CRON_NAME))


@task
@roles(settings.WEB_HOSTGROUP)
@parallel(pool_size=len(settings.WEB_HOSTGROUP) / 2)
def restart_workers():
    for gservice in settings.GUNICORN:
        run("/sbin/service %s graceful" % gservice)
    restarts = []
    for g in get_setting('MULTI_GUNICORN', []):
        restarts.append('( supervisorctl restart {0}-a; '
                        'supervisorctl restart {0}-b )&'.format(g))

    if restarts:
        run('%s wait' % ' '.join(restarts))


@task
@roles(settings.CELERY_HOSTGROUP)
@parallel
def update_celery():
    if getattr(settings, 'CELERY_SERVICE_PREFIX', False):
        run("/sbin/service %s restart" % settings.CELERY_SERVICE_PREFIX)
        run("/sbin/service %s-devhub restart" %
            settings.CELERY_SERVICE_PREFIX)
        run("/sbin/service %s-bulk restart" %
            settings.CELERY_SERVICE_PREFIX)
    if getattr(settings, 'CELERY_SERVICE_MKT_PREFIX', False):
        run("/sbin/service %s restart" %
            settings.CELERY_SERVICE_MKT_PREFIX)


@task
def deploy():
    ref = get_version()
    rpmbuild = RPMBuild(name='zamboni',
                        env=ENV,
                        ref=ref,
                        build_id=BUILD_ID,
                        cluster=CLUSTER,
                        domain=DOMAIN)

    execute(install_cron)

    rpmbuild.build_rpm(ROOT, ['zamboni', 'venv'])
    execute(install_package, rpmbuild)

    execute(restart_workers)
    rpmbuild.clean()
    with lcd(ZAMBONI):
        local('%s manage.py cron cleanup_validation_results' %
              settings.PYTHON)


@task
def pre_update(ref=settings.UPDATE_REF):
    local('date')
    execute(disable_cron)
    execute(helpers.git_update, ZAMBONI, ref)
    execute(update_info, ref)


@task
def update():
    execute(create_virtualenv)
    execute(update_locales)
    execute(update_products)
    execute(compress_assets)
    execute(compress_assets, arg='--settings=settings_local_mkt')
    execute(schematic)
    with lcd(ZAMBONI):
        local('%s manage.py dump_apps' % settings.PYTHON)
        local('%s manage.py statsd_ping --key=update' % settings.PYTHON)
