import os
from subprocess import call

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import git


path = lambda *a: os.path.join(settings.MEDIA_ROOT, *a)


class Command(BaseCommand):  #pragma: no cover
    help = ("Compresses css and js assets defined in settings.MINIFY_BUNDLES")

    requires_model_validation = False

    def handle(self, **options):
        jar_path = (os.path.dirname(__file__), '..', '..', 'bin',
                'yuicompressor-2.4.2.jar')
        path_to_jar = os.path.realpath(os.path.join(*jar_path))

        for ftype, bundle in settings.MINIFY_BUNDLES.iteritems():
            for name, files in bundle.iteritems():
                concatted_file = path(ftype, '%s-all.%s' % (name, ftype,))
                compressed_file = path(ftype, '%s-min.%s' % (name, ftype,))
                real_files = [path(f.lstrip('/')) for f in files]

                # Concats the files.
                call("cat %s > %s" % (' '.join(real_files), concatted_file),
                     shell=True)

                # Compresses the concatenation.
                call("%s -jar %s %s -o %s" % (settings.JAVA_BIN, path_to_jar,
                    concatted_file, compressed_file), shell=True)

        build_id_file = os.path.realpath(os.path.join(
            settings.ROOT, 'build.py'))

        gitid = lambda path: git.repo.Repo(os.path.join(settings.ROOT,
                path)).log( 'master')[0].id_abbrev

        with open(build_id_file, 'w') as f:
            f.write('BUILD_ID_CSS = "%s"' % gitid('media/css'))
            f.write("\n")
            f.write('BUILD_ID_JS = "%s"' % gitid('media/js'))
            f.write("\n")
