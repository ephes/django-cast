Setting up your production machine on EC2
=========================================

Creating your machine on EC2
----------------------------

* Generate keypair for your machine
* Use the Ubuntu 16.04 image
* Add rules to security policy to allow ssh/http/https for inbound traffic
* Assign an elastic ip to your instance

Install required software to run your docker deployment
-------------------------------------------------------

Switch to root user:

.. code-block:: shell

    sudo su -


Update software on the image:

.. code-block:: shell

    apt update && apt dist-upgrade

Install `Docker`_, `Supervisor`_ and docker-compose to be able to run your production deployment automatically:

.. _Docker: https://www.docker.com/
.. _Supervisor: http://supervisord.org/

.. code-block:: shell

    apt install python3 python3-pip docker.io supervisor docker-compose

Make supervisorctl accessible for normal users
----------------------------------------------

Change the line chmod=0700 to chmod=0766 in /etc/supervisor/supervisord.conf

Make docker-compose runable as normal user
-------------------------------------------

Add the default ubuntu EC2 user to /etc/group to make docker-compose executable by ubuntu.

.. code-block:: shell

    usermod -a -G docker ubuntu

Reboot
------

Reboot the machine:

.. code-block:: shell

    shutdown -r now

Check out source
----------------

Clone `foobar`_ repository into site directory:

.. _foobar : https://github.com/your_github_username/foobar.git


.. code-block:: shell

    git clone git@github.com:your_github_username/foobar.git site


Convenience
------------
Add 'cd site' at the and of ~/.bashrc to automatically switch into the project directory on login.


Keeping the service running with supervisor
-------------------------------------------

Create a link to supervisor.conf:

.. code-block:: shell

    sudo su -
    cd /etc/supervisor/conf.d/
    ln -s /home/ubuntu/site/foobar.conf foobar.conf
    /etc/init.d/supervisor restart

Set the environment variables
-----------------------------

Use the env.example template to set the production environment variables in
.env.

Starting the docker containers manually
---------------------------------------

Make sure the containers are build and the the database relations are
created.

.. code-block:: shell

    cd site
    docker-compose -f production.yml build
    docker-compose -f production.yml run django ./manage.py migrate
    docker-compose -f production.yml up

Using supervisorctl
-------------------

Check the service is now running via supervisorctl:

.. code-block:: shell

    supervisorctl start foobar
    supervisorctl status foobar
