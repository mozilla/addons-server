import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commander.deploy import hostgroups, task

import commander_settings as settings


_src_dir = lambda *p: os.path.join(settings.SRC_DIR, *p)


def git_update(ctx, ref):
    ctx.local("git fetch -t")
    ctx.local("git checkout -f %s" % ref)
    ctx.local("git submodule sync")
    ctx.local("git submodule update --init")


@task
def update_locales(ctx):
    with ctx.lcd(_src_dir("locale")):
        ctx.local("svn revert -R .")
        ctx.local("svn up")
        ctx.local("./compile-mo.sh .")


@task
def compress_assets(ctx, arg=''):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("python2.6 manage.py compress_assets %s" % arg)


@task
def schematic(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("python2.6 ./vendor/src/schematic/schematic migrations")


@task
def update_code(ctx, ref='origin/master', vendor_ref='origin/master'):
    with ctx.lcd(settings.SRC_DIR):
        git_update(ctx, ref)

        if vendor_ref:
            with ctx.lcd("vendor"):
                git_update(ctx, vendor_ref)


@task
def update_info(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local("git status")
        ctx.local("git log -1")
        ctx.local("/bin/bash -c 'source /etc/bash_completion.d/git && __git_ps1'")
        ctx.local('git show -s origin/master --pretty="format:%h" > media/git-rev.txt')


@task
def checkin_changes(ctx):
    ctx.local("/usr/bin/rsync -aq --exclude '.git*' --delete %s/ %s/" % (settings.SRC_DIR, settings.WWW_DIR))
    with ctx.lcd(settings.WWW_DIR):
        ctx.local('git add .')
        ctx.local('git commit -q -a -m "push"')


@task
def disable_cron(ctx):
    ctx.local("rm -f /etc/cron.d/%s" % settings.CRON_NAME)


@task
def install_cron(ctx):
    with ctx.lcd(settings.SRC_DIR):
        ctx.local('./scripts/crontab/gen-cron.py -z %s -r %s/bin -u apache > /etc/cron.d/.%s' %
                  (settings.SRC_DIR, settings.REMORA_DIR, settings.CRON_NAME))
        ctx.local('mv /etc/cron.d/.%s /etc/cron.d/%s' % (settings.CRON_NAME, settings.CRON_NAME))


@hostgroups(settings.WEB_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def deploy_app(ctx):
    checkin_changes()
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    ctx.remote("/bin/touch %s" % settings.REMOTE_WSGI)


@hostgroups(settings.CELERY_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def update_celery(ctx):
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    ctx.remote("/sbin/service %s restart" % settings.CELERY_SERVICE_PREFIX)
    ctx.remote("/sbin/service %s-devhub restart" % settings.CELERY_SERVICE_PREFIX)
    ctx.remote("/sbin/service %s-bulk restart" % settings.CELERY_SERVICE_PREFIX)


@task
def deploy(ctx):
    install_cron()
    deploy_app()
    update_celery()


@task
def pre_update(ctx):
    disable_cron()
    update_code(settings.UPDATE_BRANCH)


@task
def update(ctx):
    update_locales()
    compress_assets()
    schematic()
