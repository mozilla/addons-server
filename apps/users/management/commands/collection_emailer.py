import logging

from django.core.management.base import BaseCommand
from django.core import mail
from django.utils import encoding

import jingo

from amo.utils import chunked

log = logging.getLogger('z.mailer')


class Command(BaseCommand):
    args = '[no really]'
    help = "Send the email for bug 574277, but only with the args 'no really'"

    def handle(self, *args, **options):
        backend = None
        if ' '.join(args) != 'no really':
            backend = 'django.core.mail.backends.console.EmailBackend'
        log.info('Using email backend: %r' % (backend or 'default'))
        cxn = mail.get_connection(backend=backend)
        sendmail(cxn)


def sendmail(cxn):
    from bandwagon.models import Collection, CollectionUser
    owners = set(Collection.objects.values_list('author', flat=True))

    # Grab all the publishers now instead of doing one query per email.
    publishers, published = {}, {}
    pubs = dict((c.id, c) for c in
                 Collection.objects.filter(users__id__isnull=False))
    for cu in CollectionUser.objects.select_related('user'):
        publishers.setdefault(cu.collection_id, []).append(cu.user)
        published.setdefault(cu.user_id, []).append(pubs[cu.collection_id])

    ids = owners | set(published)
    log.info('We have %s emails to send.' % len(ids))

    for chunk in chunked(list(ids), 300):
        send_to_ids(chunk, published, publishers, cxn)


SUBJECT = 'Upcoming changes to your collections'
FROM = 'Mozilla Add-ons <nobody@mozilla.org>'
counter = 0
def send_to_ids(ids, published, publishers, cxn):
    from bandwagon.models import Collection
    global counter
    qs = Collection.uncached.select_related('user')
    users = {}
    for c in qs.filter(author__in=ids):
        users.setdefault(c.author, []).append(c)

    for user, cs in users.items():
        cs.extend(published.get(user.id, []))
        try:
            msg = fmt(cs, publishers)
            mail.send_mail(SUBJECT, msg, FROM, [user.email], connection=cxn)
            log.info('%s. sent to %s' % (counter, user.id))
        except Exception, e:
            log.info('%s. FAIL: (%s) %s' % (counter, user.id, e))
        counter += 1


def fmt(collections, publishers):
    return blahblah % template.render(locals())


# The template looks weird to get email whitespace right.
jingo.env.autoescape = False
template = jingo.env.from_string(u"""\
{% macro user(u) %}
{{ u.name }} {{ u.get_url_path()|absolutify }}
{% endmacro %}
{% for collection in collections %}
* {{ collection.name }}
** Owner: {{ user(collection.author) }}{% for pub in publishers[collection.id] -%}** Publisher: {{ user(pub) }}{%- endfor %}
** Current URL: {{ ('/collection/' + collection.url_slug)|absolutify }}
** New URL: {{ collection.get_url_path()|absolutify }}
{% if not loop.last %}

{% endif %}
{% endfor %}
""")


blahblah = u"""\
Dear collection owner,

We're making some changes to the way add-on collections work that will affect
how your collection is accessed and managed.

Collections will now primarily be associated with only one user. If your
collection has multiple users with access, the first owner will remain and all
other users will have access level reduced to Publisher.

Collections will also get new URLs based on the single owner's nickname. Old
URLs will still work for a while, but the new URLs should be used when linking
to your collection.

The following is a list of your collections and who the owner will be after
these changes take place, along with the new URL:

%s
We expect these changes to take place in the next few weeks. Please see our FAQ
below if you have any questions.

Thanks for creating a collection and sharing add-ons!

The Mozilla Add-ons Team

---

FAQ:
How can I change who the new owner will be?
If the owner listed above is not who should inherit the collection, the easiest
way to change that is to demote everyone except the new owner to the role of
publisher right now. When the new system takes effect, the single owner will
remain owner.

How can I change what my collection's URL will be?
The collection URL is based on the owner's nickname and the collection's
nickname. If either of those listed above should be something else, you can
change them now.

What if I have another question?
You can ask for help in our forums: https://forums.addons.mozilla.org
"""
