
=======================================
Installing Zamboni In A VM With Vagrant
=======================================

Instead of :doc:`installing Zamboni piecemeal <installation>`
you can set it up in a virtual machine. This is an ideal way to
get up and running quickly and to keep your dev system clean.

Requirements
------------
To get started, you'll need:

 * `git <http://git-scm.com/>`_

   * On Mac OS X with `homebrew <http://mxcl.github.com/homebrew/>`_,
     run ``brew install git``

 * `VirtualBox <https://www.virtualbox.org/wiki/Downloads>`_

   * The desktop installer walks you through it.

 * `vagrant <http://vagrantup.com/>`_ 0.8.10 (not 0.9.*)

   * gem is included with Mac OS X. Otherwise you may need to install
     `Ruby <http://www.ruby-lang.org/>`_ and `gem <http://rubygems.org/>`_.
   * If it's your first time using Ruby you should probably run
     ``sudo gem update --system``
   * To install vagrant 0.8 run ``sudo gem install vagrant -v '= 0.8.10'``

If you get stuck, see the Troubleshooting section below.

Get The Source
--------------

Clone the Zamboni repository::

    cd ~
    git clone --recursive git://github.com/mozilla/zamboni.git

This takes about a minute and puts the source code in a directory called
``zamboni``.

Build the VM
------------

Change into the source code directory and start the VM with vagrant::

    cd zamboni
    vagrant up

After about 5-10 minutes, depending on your Internet connection, vagrant
downloads the base VM image, boots an Ubuntu VM, installs required packages, and
runs initialization scripts.

Start The Dev Server
--------------------

Now that your VM is running, SSH in and start the server::

    vagrant ssh
    ./project/vagrant/bin/start.sh

On your first run, this will take several minutes because it pulls down some
JSON data files. On subsequent runs it should start up within a minute.
Your development server will then be running on a special IP address created
by vagrant. Yay. To access it, open a web browser to http://33.33.33.24:8000/

You can make an alias to this IP address by adding the following line to your
``/etc/hosts`` file::

    33.33.33.24    z.local

After that, you can access the server at http://z.local:8000/

Suspending/Resuming the VM
--------------------------

To conserve system resources you can suspend the VM like::

    cd zamboni
    vagrant suspend

Then when you want to use it again just type::

    vagrant resume

This boots up the VM in the state it was left in but you still have to SSH in
and start up the dev server with the command above.

Updating Zamboni Code
---------------------

To sync your repository with upstream changes, just update the code using git::

    cd zamboni
    git pull && git submodule sync --quiet && git submodule update --init --recursive

Next, rebuild your VM so that any new requirements are installed and any new
DB migration scripts are run.

Rebuilding your VM
------------------

You can re-run all installation steps with the reload command. If a package is
already installed in the VM it will not be re-installed (so it's a bit faster).
::

    cd zamboni
    vagrant reload

However, it may not always work. To completely destroy your VM and start from
scratch (that is, besides downloading the base disk image) you can do this::

    vagrant destroy && vagrant up

It's a little slower but not as slow as when you first ran it. Now you can SSH
in and restart the dev server with the same command from above.

Customizing Your VM
-------------------

You can always ``vagrant ssh`` into the box and change whatever you want.
This will persist as long as you don't halt/reload the VM.

To make a permanent change to how your VM is built, copy ``custom.pp`` and
add puppet commands like
`exec <http://docs.puppetlabs.com/references/2.7.0/type.html#exec>`_ to it::

    cp vagrant/manifests/classes/custom-dist.pp vagrant/manifests/classes/custom.pp

For example, if your ``settings_local.py`` file requires additional packages or
Python modules, you'll need to add ``sudo pip install <package>``.
Your ``custom.pp`` file is ignored by git.

Troubleshooting
---------------

If you're using vagrant 0.9 you need to downgrade to 0.8.10 because of
`this bug <https://github.com/mitchellh/vagrant/issues/516>`_.

You might see an error like this when first running vagrant::

    /Library/Ruby/Gems/1.8/gems/net-ssh-2.1.4/lib/net/ssh/key_factory.rb:38:in `read': Permission denied - /Library/Ruby/Gems/1.8/gems/vagrant-0.8.

It was fixed in `issue 580 <https://github.com/mitchellh/vagrant/issues/580>`_
but until we can run vagrant 0.9 you can fix it with this::

    sudo chmod 644 /Library/Ruby/Gems/1.8/gems/vagrant-0.8.10/keys/vagrant


If you have already set up Zamboni with a custom ``settings_local.py`` file
then be sure your database credentials match the defaults::

    'NAME': 'zamboni',
    'USER': 'root',
    'PASSWORD': '',
    ...

Otherwise you'll probably see database errors.
