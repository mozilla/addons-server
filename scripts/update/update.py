import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commander.deploy import hostgroups, task

import commander_settings as settings


_src_dir = lambda *p: os.path.join(settings.SRC_DIR, *p)


@task
def create_virtualenv(ctx):
    venv = settings.VIRTUAL_ENV
    ctx.local("rm -f %s/lib64" % venv)
    ctx.local("virtualenv --distribute --never-download %s" % venv)
    ctx.local("rm -f %s/lib64 && ln -s ./lib %s/lib64" % (venv, venv))

    ctx.local("%s/bin/pip install --exists-action=w --no-deps --download-cache=/tmp/pip-cache -i %s -r %s/requirements/prod.txt" %
                (venv, settings.PYPI_MIRROR, settings.SRC_DIR))

    ctx.local("rm -f %s/lib/python2.6/no-global-site-packages.txt" % venv)
    ctx.local("%s/bin/python /usr/bin/virtualenv --relocatable %s" % (venv, venv))


@task
def update_locales(ctx):
    with ctx.lcd(_src_dir("locale")):
        ctx.local("svn revert -R .")
        ctx.local("svn up")
        ctx.local("./compile-mo.sh .")


@task
def update_products(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('%s manage.py update_product_details' % settings.PYTHON)


@task
def compress_assets(ctx, arg=''):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("%s manage.py compress_assets %s" % (settings.PYTHON, arg))


@task
def schematic(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("%s ./vendor/src/schematic/schematic migrations" % settings.PYTHON)


@task
def update_code(ctx, ref='origin/master'):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("git fetch && git fetch -t")
        ctx.local("git checkout -f %s" % ref)
        ctx.local("git submodule sync")
        ctx.local("git submodule update --init --recursive")
        # Recursively run submodule sync and update to get all the right repo URLs.
        ctx.local("git submodule foreach 'git submodule sync --quiet'")
        ctx.local("git submodule foreach 'git submodule update --init --recursive'")


@task
def update_info(ctx, ref='origin/master'):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("git status")
        ctx.local("git log -1")
        ctx.local("/bin/bash -c 'source /etc/bash_completion.d/git && __git_ps1'")
        ctx.local('git show -s {0} --pretty="format:%h" > media/git-rev.txt'.format(ref))


@task
def checkin_changes(ctx):
    ctx.local(settings.DEPLOY_SCRIPT)


@task
def disable_cron(ctx):
    ctx.local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('%s ./scripts/crontab/gen-cron.py -z %s -r %s/bin -u apache -p %s > /etc/cron.d/.%s' %
                  (settings.PYTHON, settings.SRC_DIR, settings.REMORA_DIR, settings.PYTHON, settings.CRON_NAME))
        ctx.local('mv /etc/cron.d/.%s /etc/cron.d/%s' % (settings.CRON_NAME, settings.CRON_NAME))


@hostgroups(settings.WEB_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def deploy_app(ctx):
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    if getattr(settings, 'GUNICORN', False):
        for gservice in settings.GUNICORN:
            ctx.remote("/sbin/service %s graceful" % gservice)
    else:
        ctx.remote("/bin/touch %s/wsgi/zamboni.wsgi" % settings.REMOTE_APP)
        ctx.remote("/bin/touch %s/wsgi/mkt.wsgi" % settings.REMOTE_APP)
        ctx.remote("/bin/touch %s/services/wsgi/verify.wsgi" % settings.REMOTE_APP)
        ctx.remote("/bin/touch %s/services/wsgi/application.wsgi" % settings.REMOTE_APP)


@hostgroups(settings.CELERY_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def update_celery(ctx):
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    if getattr(settings, 'CELERY_SERVICE_PREFIX', False):
        ctx.remote("/sbin/service %s restart" % settings.CELERY_SERVICE_PREFIX)
        ctx.remote("/sbin/service %s-devhub restart" % settings.CELERY_SERVICE_PREFIX)
        ctx.remote("/sbin/service %s-bulk restart" % settings.CELERY_SERVICE_PREFIX)
    if getattr(settings, 'CELERY_SERVICE_MKT_PREFIX', False):
        ctx.remote("/sbin/service %s restart" % settings.CELERY_SERVICE_MKT_PREFIX)


@task
def deploy(ctx):
    install_cron()
    checkin_changes()
    deploy_app()
    update_celery()
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('%s manage.py cron cleanup_validation_results' % settings.PYTHON)


@task
def pre_update(ctx, ref=settings.UPDATE_REF):
    ctx.local('date')
    disable_cron()
    update_code(ref)
    update_info(ref)


@task
def update(ctx):
    create_virtualenv()
    update_locales()
    update_products()
    compress_assets()
    compress_assets(arg='--settings=settings_local_mkt')
    schematic()
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('%s manage.py --settings=settings_local_mkt build_appcache' % settings.PYTHON)
        ctx.local('%s manage.py dump_apps' % settings.PYTHON)
        ctx.local('%s manage.py statsd_ping --key=update' % settings.PYTHON)
