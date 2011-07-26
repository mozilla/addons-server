import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from commander.deploy import hosts, hostgroups, task

import commander_settings as settings



def git_update(ctx, branch):
    ctx.local("git fetch")
    ctx.local("git checkout -f origin/%s" % branch)
    ctx.local("git submodule sync")
    ctx.local("git submodule update --init")


def update_locales(ctx):
    with ctx.lcd("locale"):
        ctx.local("svn revert -R .")
        ctx.local("svn up")
        ctx.local("./compile-mo.sh .")


@task
def update_zamboni(ctx, branch):
    print "Updating Zamboni: %s" % datetime.now()
    with ctx.lcd(settings.SRC_DIR):
        git_update(ctx, branch)
        update_locales(ctx)

        with ctx.lcd("vendor"):
            git_update(ctx, "master")

        ctx.local("/usr/bin/python2.6 manage.py compress_assets")
        ctx.local("/usr/bin/python2.6 ./vendor/src/schematic/schematic migrations")

        # INFO
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


@hostgroups(settings.WEB_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def deploy_app(ctx):
    checkin_changes()
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    ctx.remote("/bin/touch %s" % settings.REMOTE_WSGI)


@hostgroups(settings.CELERY_HOSTGROUP, remote_kwargs={'ssh_key': settings.SSH_KEY})
def update_gearman(ctx):
    ctx.remote(settings.REMOTE_UPDATE_SCRIPT)
    ctx.remote("/sbin/service %s restart" % settings.CELERY_SERVICE_PREFIX)
    ctx.remote("/sbin/service %s-devhub restart" % settings.CELERY_SERVICE_PREFIX)
    ctx.remote("/sbin/service %s-bulk restart" % settings.CELERY_SERVICE_PREFIX)


@task
def update_all(ctx):
    update_zamboni(settings.UPDATE_BRANCH)
    deploy_app()
    update_gearman()
