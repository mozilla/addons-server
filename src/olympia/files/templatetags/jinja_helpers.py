from django.template import loader

import jinja2

from django_jinja import library


@library.global_function
def file_viewer_class(value, key):
    result = []
    if value['directory']:
        result.append('directory closed')
    else:
        result.append('file')
    if value['short'] == key:
        result.append('selected')
    if value.get('diff'):
        result.append('diff')
    return ' '.join(result)


@library.global_function
def file_tree(files, selected):
    depth = 0
    output = ['<ul class="root">']
    t = loader.get_template('files/node.html')
    for k, v in sorted(files.items()):
        if v['depth'] > depth:
            output.append('<ul class="">')
        elif v['depth'] < depth:
            output.extend(['</ul>' for x in range(v['depth'], depth)])
        output.append(t.render({'value': v, 'selected': selected}))
        depth = v['depth']
    output.extend(['</ul>' for x in range(depth, -1, -1)])
    return jinja2.Markup('\n'.join(output))
