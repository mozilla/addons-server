.. _export:

======
Export
======

There is an export of nightly data that is available as a tarball. The download
can be found at the following URLs:

* Development server: https://marketplace-dev-cdn.allizom.org/dumped-apps/tarballs/YYYY-MM-DD.tgz

Contents:

* *readme.txt* and *license.txt*: information about the export.

* *apps*: this directory contains all the exported apps. Each app is a seperate
  JSON file and contains the output of :ref:`the app GET method <app-response-label>`

Caveats:

* An app must be public to be exported, which means apps may be removed as
  their status on the marketplace changes.

* No user object is present, so user specific information about the app is not
  present.

* The export has no locale, region or carrier specified. It defaults to the
  region ``worldwide`` and locale ``en-US``.
