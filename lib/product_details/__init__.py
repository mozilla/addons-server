"""
The /json dir here is a git-svn submodule of
http://svn.mozilla.org/libs/product-details/json/.

When this module is imported, we load all the .json files and insert them as
module attributes using locals().  It's a magical and wonderful process.
"""
import json
import os


root = os.path.dirname(os.path.realpath(__file__))
json_dir = os.path.join(root, 'json')

for filename in os.listdir(json_dir):
    if filename.endswith('.json'):
        name = os.path.splitext(filename)[0]
        path = os.path.join(json_dir, filename)
        locals()[name] = json.load(open(path))
