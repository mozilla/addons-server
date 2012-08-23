import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commander.deploy import hostgroups, task

import commander_settings as settings


_src_dir = lambda *p: os.path.join(settings.SRC_DIR, *p)


@task
def update_locales(ctx):
    with ctx.lcd(_src_dir("locale")):
        ctx.local("svn revert -R .")
        ctx.local("svn up")
        ctx.local("./compile-mo.sh .")


@task
def update_products(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('python2.6 manage.py update_product_details')


@task
def compress_assets(ctx, arg=''):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("python2.6 manage.py compress_assets %s" % arg)


@task
def schematic(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("python2.6 ./vendor/src/schematic/schematic migrations")


@task
def update_code(ctx, ref='origin/master'):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("git fetch && git fetch -t")
        ctx.local("git checkout -f %s" % ref)
        ctx.local("git submodule sync")
        # `submodule sync` doesn't do `--recursive` yet. (P.S. We `sync` twice
        # to git around the git bug 'fatal: reference not in tree'.)
        ctx.local("git submodule --quiet foreach 'git submodule --quiet sync "
                  "&& git submodule --quiet sync "
                  "&& git submodule update --init --recursive'")
        ctx.local("git submodule update --init --recursive")  # at the top


@task
def update_remora(ctx):
    with ctx.lcd(settings.REMORA_DIR):
        ctx.local('svn revert -R .')
        ctx.local('svn up')


@task
def update_info(ctx, ref='origin/master'):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("git status")
        ctx.local("git log -1")
        ctx.local("/bin/bash -c 'source /etc/bash_completion.d/git && __git_ps1'")
        ctx.local('git show -s {0} --pretty="format:%h" > media/git-rev.txt'.format(ref))


@task
def checkin_changes(ctx):
    ctx.local("/usr/bin/rsync -aq --exclude '.git*' --delete %s/ %s/" % (settings.SRC_DIR, settings.WWW_DIR))


@task
def disable_cron(ctx):
    ctx.local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('python2.6 ./scripts/crontab/gen-cron.py -z %s -r %s/bin -u apache > /etc/cron.d/.%s' %
                  (settings.SRC_DIR, settings.REMORA_DIR, settings.CRON_NAME))
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
        ctx.local('python2.6 manage.py cron cleanup_validation_results')


@task
def pre_update(ctx, ref=settings.UPDATE_REF):
    ctx.local('date')
    disable_cron()
    update_code(ref)
    update_info(ref)


@task
def update(ctx):
    update_locales()
    update_products()
    compress_assets()
    compress_assets(arg='--settings=settings_local_mkt')
    schematic()
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('python2.6 manage.py --settings=settings_local_mkt build_appcache')
        ctx.local('python2.6 manage.py dump_apps')
        ctx.local('python2.6 manage.py statsd_ping --key=update')
