===================================
Get Started With Vagrant On Windows
===================================

Here is a guide to help you get started installing Olympia inside a vagrant virtual machine on Windows. Once you're done, you can go back to :doc:`installing Olympia with vagrant <install-with-vagrant>`.

Install Virtual Box
===================

Download and install Oracle's VirtualBox if you haven't already.
http://www.virtualbox.org/

Install Git
===========

Download and install mysysgit from: http://code.google.com/p/msysgit/downloads/list
This is needed so that Windows has git capablity.

In Git Setup you need to choose the following options:

 * On "Adjusting your PATH environment" dialog choose "Run Git from the Windows Command Prompt".
 * On "Choosing the SSH executable" dialog choose "Use OpenSSH".
 * **IMPORTANT**: On "Configuring the line ending conversions" dialog choose "Checkout as-is, commit Unix-style line ending".

Install Ruby
============

Download and install RubyInstaller from: http://rubyinstaller.org/downloads/
Make sure to select option to add ruby path executable paths.

Download and extract Development Kit from above URL. Probably easiest to extract to ``C:\DevKit``

Then follow developer kit installation instructions at:  https://github.com/oneclick/rubyinstaller/wiki/Development-Kit

Summary of instructions:

 * Using command prompt cd folder development kit was extracted into (e.g. cd ``c:\DevKit``)
 * Run the command ``ruby dk.rb init``. Then run the command ``ruby dk.rb install`` to install rubygems.
 * Confirm installation by running the following commands:

   * ``gem install rdiscount --platform=ruby``
   * ``ruby -rubygems -e "require 'rdiscount'; puts RDiscount.new('**Hello RubyInstaller**').to_html"`` command prompt should echo out ``<p><strong>Helo RubyInstaller </strong></p>``

Install Vagrant
===============

Run the command ``gem install vagrant``

.. note::

    If you are running 64bit Windows you MUST use v0.9.6 or above otherwise Virtual Box will not be detected properly.

Get Olympia Code
================

cd to the folder above where you want the olympia folder and files to be placed (e.g. ``c:\``)
Run the command ``git clone --recursive git://github.com/mozilla/olympia.git``
This will take some time, go get a cup of coffee, eat lunch, go for a walk, etc.

In the olympia folder (e.g. ``c:\olympia``) find the file ``Vagrantfile`` and open it in your favorite text editor.

Look for the following lines::

    # For convenience add something like this to /etc/hosts: 33.33.33.24 z.local
    # config.vm.network :hostonly, "33.33.33.24"
    config.vm.network "33.33.33.24"  # old 0.8.* way


Change them to::

    # For convenience add something like this to /etc/hosts: 33.33.33.24 z.local
    config.vm.network :hostonly, "33.33.33.24"
    #config.vm.network "33.33.33.24"  # old 0.8.* way

Start The Olympia VM
====================

It is time to build your olympia virtual machine.  In the command prompt, cd to the olympia folder (e.g. cd ``c:\olympia``) and run the command ``vagrant up``. This step will download the olympia virtual machine from Mozilla and install it. Before warned that this archive is many hundred megabytes in size so it will take some time to download even if you are on a broadband connection.

Configure SSH
~~~~~~~~~~~~~

Download PuTTY SSH client and PuTTYgen from http://www.chiark.greenend.org.uk/~sgtatham/putty/download.html. These are standalone executable files. You need to save them in their permanent location, (e.g. ``C:\Program Files (x86)\Putty``).

You need to generate a private key for PuTTY. To do this, launch PuTTYgen and click on the "generate" button. You will be instructed to randomly move your mouse around the PuTTYgen window to generate the key. Once this is done, click on "load" and find the file "insecure_private_key", it will probably be in your user folder under ".vagrant.d" (e.g. on Win7 at ``C:\Users\{your username}\.vagrant.d``). Now save your public key and then save your private key (use different file names for each).

Create a PuTTY SSH session for olympia. Launch PuTTY. In the host name put "127.0.0.1" and in the port use "2222". In the category pane find "data" under "connection" and place "vagrant" in the auto-login username field. Then expand out the "SSH" branch and select "auth". Next to the "private key file for authentication" field click on browse and find the private key you just generated. Select it and click "open" in the folder browser window. Now go back to "session" in the category pane in PuTTY, add "vagrant" to the saved sessions field and then click "save". This will save your session for future use.

Login to olympia by clicking on "open" in the PuTTY window.  This should automatically log you into the Olympia VM.  If you add the PuTTY file path to your system properties environment variable "path" (e.g. ``;C:\Program Files (x86)\Putty``) you should be able to reference PuTTY from the command prompt by simply calling "putty -load vagrant" once you reboot your computer.

The first time you log into Olympia you should see a very long series of scrolling text with lots of SQL statements etc.  This is the database migrations taking place. This phase could take quite a while to complete. Don't do anything to your PuTTY VM session until it gives you back a command prompt.

Congratulations if things went well your Olympia VM is up and running. You are now ready to start the Dev Server.

Start the Dev Server
~~~~~~~~~~~~~~~~~~~~

From PuTTY VM session, enter the command ``./project/vagrant/bin/start.sh``.

You should now be able to access your development server on a special IP address set up by Vagrant.  Point your web browser to http://33.33.33.24:8000/

More info on :doc:`installing Olympia with vagrant <install-with-vagrant>`.
