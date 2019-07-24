==========================
Adding Python Dependencies
==========================

To add a new dependency you'll to carry out the following.
First install hashin::

    pip install hashin

Next add the dependency you want to add to the relevant requirements file.

.. note::
    If you add just the package name the script will automatically get the
    latest version for you.

Once you've done that you can run the requirements script::

    hashin -r <requirements file> <dependency>

This will add hashes and sort the requirements for you adding comments to
show any package dependencies.

When it's run check the diff and make edits to fix any issues before
submitting a PR with the additions.
