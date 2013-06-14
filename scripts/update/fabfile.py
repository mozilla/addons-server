import os
import time
from fabric.api import env, execute, lcd, local, put, run, roles, task

import commander.hosts
import commander_settings as settings


env.key_filename = settings.SSH_KEY
env.roledefs.update(commander.hosts.hostgroups)

_src_dir = lambda *p: os.path.join(settings.SRC_DIR, *p)
ROOT_DIR = os.path.dirname(settings.SRC_DIR)
VIRTUALENV = os.path.join(ROOT_DIR, 'venv')

BUILD_ID = str(int(time.time()))
INSTALL_TO = os.path.join(os.path.dirname(settings.WWW_DIR), BUILD_ID)
PACKAGE_DIR = '/tmp'


def setup_notifier():
    notifier_endpoint = getattr(settings, 'NOTIFIER_ENDPOINT', None)
    notifier_key = getattr(settings, 'NOTIFIER_KEY', None)
    null_notify = lambda a: None
    if not notifier_endpoint:
        return null_notify

    try:
        import pushbotnotify
    except ImportError:
        return null_notify

    notifier = pushbotnotify.Notifier(endpoint=notifier_endpoint,
                                      api_key=notifier_key)

    return notifier.notify


notify = setup_notifier()


@task
def create_virtualenv():
    with lcd(settings.SRC_DIR):
        status = local('git diff HEAD@{1} HEAD --name-only')

    if 'requirements/' in status:
        venv = VIRTUALENV
        if not venv.startswith('/data'):
            raise Exception('venv must start with /data')

        local('rm -rf %s' % venv)
        local('virtualenv --distribute --never-download %s' % venv)

        local('%s/bin/pip install --exists-action=w --no-deps --no-index '
              '--download-cache=/tmp/pip-cache -f %s '
              '-r %s/requirements/prod.txt' %
              (venv, settings.PYREPO, settings.SRC_DIR))

        if getattr(settings, 'LOAD_TESTING', False):
            local('%s/bin/pip install --exists-action=w --no-deps '
                  '--no-index --download-cache=/tmp/pip-cache -f %s '
                  '-r %s/requirements/load.txt' %
                  (venv, settings.PYREPO, settings.SRC_DIR))

        # make sure this always runs
        local("rm -f %s/lib/python2.6/no-global-site-packages.txt" % venv)
        local("%s/bin/python /usr/bin/virtualenv --relocatable %s" %
              (venv, venv))


@task
def update_locales():
    with lcd(_src_dir("locale")):
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
    with lcd(settings.SRC_DIR):
        local('%s manage.py update_product_details' % settings.PYTHON)


@task
def compress_assets(arg=''):
    with lcd(settings.SRC_DIR):
        local("%s manage.py compress_assets -t %s" % (settings.PYTHON,
                                                      arg))


@task
def schematic():
    with lcd(settings.SRC_DIR):
        local("%s %s/bin/schematic migrations" %
              (settings.PYTHON, VIRTUALENV))


@task
def update_code(ref='origin/master'):
    with lcd(settings.SRC_DIR):
        local("git fetch && git fetch -t")
        local("git reset --hard %s" % ref)
        local("git submodule sync")
        local("git submodule update --init --recursive")
        # Recursively run submodule sync/update to get all the right repo URLs.
        local("git submodule foreach 'git submodule sync --quiet'")
        local("git submodule foreach "
              "'git submodule update --init --recursive'")


@task
def update_info(ref='origin/master'):
    with lcd(settings.SRC_DIR):
        local("git status")
        local("git log -1")
        local("/bin/bash -c "
              "'source /etc/bash_completion.d/git && __git_ps1'")
        local('git show -s {0} --pretty="format:%h" '
              '> media/git-rev.txt'.format(ref))


@task
def build_package(name, pkgfile):
    local('fpm -s dir -t rpm -n "%s" '
          '-p "%s" '
          '-x "*.git" -x "*.svn" -x "*.pyc" '
          '-C %s --prefix "%s" zamboni venv' % (name,
                                                pkgfile,
                                                ROOT_DIR,
                                                INSTALL_TO))


@roles(settings.WEB_HOSTGROUP, settings.CELERY_HOSTGROUP)
@task
def install_package(package_file):
    cur_sym = os.path.join(os.path.dirname(INSTALL_TO), 'current')

    put(package_file, package_file)
    run('rpm -i %s' % package_file)
    run('[[ -d {0} ]] && ln -s -f {0} {1}'.format(INSTALL_TO, cur_sym))


@task
def disable_cron():
    local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron():
    with lcd(settings.SRC_DIR):
        local('%s ./scripts/crontab/gen-cron.py '
              '-z %s -r %s/bin -u apache -p %s > /etc/cron.d/.%s' %
              (settings.PYTHON, settings.SRC_DIR, settings.REMORA_DIR,
               settings.PYTHON, settings.CRON_NAME))

        local('mv /etc/cron.d/.%s /etc/cron.d/%s' % (settings.CRON_NAME,
                                                     settings.CRON_NAME))


@roles(settings.WEB_HOSTGROUP)
@task
def restart_workers():
    if getattr(settings, 'GUNICORN', False):
        for gservice in settings.GUNICORN:
            run("/sbin/service %s graceful" % gservice)
    else:
        run("/bin/touch %s/wsgi/zamboni.wsgi" % settings.REMOTE_APP)
        run("/bin/touch %s/wsgi/mkt.wsgi" % settings.REMOTE_APP)
        run("/bin/touch %s/services/wsgi/verify.wsgi" %
            settings.REMOTE_APP)
        run("/bin/touch %s/services/wsgi/application.wsgi" %
            settings.REMOTE_APP)


@roles(settings.CELERY_HOSTGROUP)
@task
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
    with lcd(settings.SRC_DIR):
        ref = local('git rev-parse HEAD', capture=True)
    ref = ref[:6]

    package_name = 'zamboni-%s-%s-%s' % (getattr(settings, 'ENV', 'dev'),
                                         BUILD_ID, ref)
    package_file = os.path.join(PACKAGE_DIR, '%s.rpm' % package_name)

    execute(install_cron)
    execute(build_package, package_name, package_file)
    execute(install_package, package_file)
    execute(restart_workers)
    with lcd(settings.SRC_DIR):
        local('%s manage.py cron cleanup_validation_results' %
              settings.PYTHON)


@task
def pre_update(ref=settings.UPDATE_REF):
    local('date')
    execute(disable_cron)
    execute(update_code, ref)
    execute(update_info, ref)


@task
def update():
    execute(create_virtualenv)
    execute(update_locales)
    execute(update_products)
    execute(compress_assets)
    execute(compress_assets, arg='--settings=settings_local_mkt')
    execute(schematic)
    with lcd(settings.SRC_DIR):
        local('%s manage.py dump_apps' % settings.PYTHON)
        local('%s manage.py statsd_ping --key=update' % settings.PYTHON)
