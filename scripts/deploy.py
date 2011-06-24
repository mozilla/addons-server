"""
A commander script to deploy AMO in production.

https://github.com/oremj/commander
"""
import os

from commander.deploy import hostgroups, task


AMO_PYTHON_ROOT = '/data/amo_python'
AMO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_amo_dir = lambda *p: os.path.join(AMO_DIR, *p)

_git_lcmd = lambda ctx, c: ctx.local("/usr/bin/git %s" % c)

def _git_checkout_tag(ctx, tag):
    _git_lcmd(ctx, "fetch -t origin")
    _git_lcmd(ctx, "checkout %s" % tag)
    _git_lcmd(ctx, "submodule sync")
    _git_lcmd(ctx, "submodule update --init")

@task
def update_code(ctx, tag, vendor_tag=None):
    with ctx.lcd(AMO_DIR):
        _git_checkout_tag(ctx, tag)

        if vendor_tag:
            with ctx.lcd("vendor"):
                _git_checkout_tag(ctx, vendor_tag)

@task
def update_locales(ctx):
    with ctx.lcd(_amo_dir(AMO_DIR, 'locale')):
        ctx.local("svn revert -R .")
        ctx.local("svn up")

@task
def disable_cron(ctx):
    ctx.local("mv /etc/cron.d/addons-prod-maint /tmp/addons-prod-maint")


@task
def enable_cron(ctx):
    with ctx.lcd(AMO_DIR):
        ctx.local("cp scripts/crontab/prod /etc/cron.d/addons-prod-maint")


def manage_cmd(ctx, command):
    """Call a manage.py command."""
    with ctx.lcd(AMO_DIR):
        ctx.local("python2.6 manage.py %s" % command)


@task
def compress_assets(ctx, arg=''):
    with ctx.lcd(AMO_DIR):
        ctx.local("python2.6 manage.py compress_assets %s" % arg)


@task
def schematic(ctx):
    with ctx.lcd(AMO_DIR):
        ctx.local("python2.6 ./vendor/src/schematic/schematic migrations")




@hostgroups(['amo_gearman'])
def restart_celery(ctx):
    ctx.remote("service celeryd-prod restart")
    ctx.remote("service celeryd-prod-devhub restart")


@hostgroups(['amo'])
def stop_appserver_cron(ctx):
    ctx.remote("service crond stop")


@hostgroups(['amo'])
def start_appserver_cron(ctx):
    ctx.remote("service crond start")


@task
def deploy_code(ctx, subdir='', reload_apache=True):
    stop_appserver_cron()
    try:
        with ctx.lcd(AMO_PYTHON_ROOT):
            src = os.path.join("src/prod/zamboni/", subdir, '')
            www = os.path.join("www/prod/zamboni/", subdir, '')

            ctx.local("/usr/bin/rsync -aq --exclude '.git*' --delete %s %s" % (src, www))
            with ctx.lcd("www"):
                ctx.local("/usr/bin/git add .")
                ctx.local("/usr/bin/git commit -q -a -m 'AMO PUSH'")
        pull_code(reload_apache)
    finally:
        start_appserver_cron()


@task
def deploy_media(ctx):
    deploy_code('media', False)


@hostgroups(['amo', 'amo_gearman'], remote_limit=5)
def pull_code(ctx, reload_apache=True):
    ctx.remote("/data/bin/libget/get-php5-www-git.sh")
    if reload_apache:
        ctx.remote("apachectl graceful")


@hostgroups(['amo_memcache'])
def clear_memcache(ctx):
    ctx.remote('service memcached restart')


@hostgroups(['amo_redis'])
def clear_redis(ctx):
    ctx.remote('pkill -9 -f "redis.*/amo.conf"; sleep 3; /etc/init.d/redis-amo start')


@task
def start_update(ctx, tag, vendor_tag):
    disable_cron()
    update_code(tag, vendor_tag)


@task
def update_amo(ctx):
    # BEGIN: The normal update/push cycle.
    update_locales()
    compress_assets()
    schematic()
    # Sync out media to all the servers first.
    deploy_media()
    enable_cron()
    deploy_code()
    restart_celery()
    # END: The normal update/push cycle.

    # Run management commands like this:
    # manage_cmd(ctx, 'cmd')
    manage_cmd(ctx, 'process_addons --task=get_preview_sizes')
