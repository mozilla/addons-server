"""
The /json dir here is a git-svn submodule of
http://svn.mozilla.org/libs/product-details/json/.

When this module is imported, we load all the .json files and insert them as
module attributes using locals().  It's a magical and wonderful process.
"""
import json
import os
import codecs

root = os.path.dirname(os.path.realpath(__file__))
json_dir = os.path.join(root, 'json')

for filename in os.listdir(json_dir):
    if filename.endswith('.json'):
        name = os.path.splitext(filename)[0]
        path = os.path.join(json_dir, filename)
        locals()[name] = json.load(open(path))


def get_regions(locale):
    """
    Get a list of region names for a specific locale as a
    dictionary with country codes as keys and localized names as
    values.
    """

    def json_file(name):
        return os.path.join(json_dir, 'regions', '%s.json' % name)

    filepath = json_file(locale)

    if not os.path.exists(filepath):
        filepath = json_file('en-US')
        if not os.path.exists(filepath):
            raise Exception('Unable to load region data')

    with codecs.open(filepath, encoding='utf8') as fd:
        return json.load(fd)
