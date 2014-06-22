============
Introduction
============

A set of primitives and building blocks to create your own PaaS system. 

It is: 

- A controller that has a lose concept of services, groups of services,
  service versions, running instances and hosts. These are mostly buckets
  of arbitrary data.

- A generic HTTP API by which these primitives can be managed.

- A backend API to interact with your actual service infrastructure.
 
- A basic client CLI framework to communicate with the API.


Plugins that build (or could be built on this API) include:

- For the backend, services could be started e.g. via CoreOS fleet, via 
  flynn-host, or on a single host using a supervisor like Upstart or
  systemd.
  
- For service discovery, you could use etcd, Consul or just DNS.
 
- For routing, you could use HAProxy, hipache, gorouter, strowger.

- For running apps via buildpacks, plugins can add support for
  slugbuilder and gitreceive.
  
- Other plugins can help you manage resources like databases.


One assumption sort of being made is that you will be using service
discovery. While in theory there is nothing stopin


Why?
====

With new technologies like Docker, CoreOS and the buildpack concept, I'd
like to think that this new style of managing services will become the
default at home. We can provide isolation and service discovery, while
actually making things easier than ssh-ing around installing packages.
  
The tooling is still in its infancy; many people use shell scripts to 
orchestrate docker. Indeed, this started as a script executing commands
over SSH. While trying to evolve it, I noticed that I had never thought
through the concepts, and just wasn't sure what I wanted, so I tried to
keep things open-ended.

I'm now cleaning it up and adding some documentation, in the hopes it 
may be useful to you as well.


Current status
--------------

So far, I'm using this to run services on a single host, using Upstart 
to supervise containers, with ``etcd/discoverd`` providing service
discovery.

The concepts relating to multi-host functionality still need to be worked
out.

Things are definitely in an early stage, still in flux, and not everything
promoted on this page has actually been implemented.


================================
How you might use it in practice
================================

The default command line is a pretty raw interface to the API::

    ./cli create-deployment foo
    ----> Created foo
    
    ./cli -D foo set-service company/redis
    ----> New instance id foo-redis-1-1
    
    ./cli -D foo set-service redis "{env: {SDF: sdf}}"
    ----> New instance id foo-redis-2-1
    
    ./cli list
    foo
        redis
            running  instance           version                
                
            
You are creating the primitives (deployment, service), the controller 
will convert them to versions and instances and run them on your cluster.

How will it run them? Have a look at the ``backends``.

Maybe you would rather define your services in a file::


    $ cat Servicefile
    Env:
        BRANDING: Company Ltd.
        
    redis:
        image: rock77/redis
        volumes: {data: /srv/redis}
        
    website:
        image: rock77/website
        cmd: /bin/runserver
        
    $ ./cli create-deployment my-site
    $ ./cli -D my-site deploy Servicefile 
    ---> ....
    $ ./cli -D my-site deploy Servicefile
    No changes.
        
    
Do you want to use buildpacks? Use the 'app' plugin.

::

    $ ./cli -D foo set-service website '{"git": "."}'
    ---> Held
    ---> Uploading
    
    $ ./cli -D foo upload website --git .
    ---> Deploying a new version 
    
    
You'd like to use 'git push' rather than uploading? The 'gitreceive'
plugin will run an ssh endpoint::

    $ ./cli -D foo set-service website '{"git": "."}'
    ---> Starting gitreceived.
    ---> Held
    ---> Adding remote deploy to repository '.'

      

================================
How you might run it in practice
================================

The two big moving parts are: service discovery, and how to schedule 
containers.


In the simplest case, we can just connect directly to Docker to run
containers. There is a plugin for that, but the approach has limitations:

- You will have to rely on the docker ``-r`` mode to restart containers 
  on host boot, and in my experience, it doesn't reliably.

- If a container crashes, it will not be restarted.

- If a host crashes, it's services will not be moved to a different one.
   
So there are some alternatives to consider.


Upstart
-------

There is a plugin to use Upstart. This only works on a single host, 
and will create an Upstart file for each instance that is supposed to
run. Upstart will ensure things stay up, through reboots and crashes.


CoreOS fleet
------------

You could use fleet to run services. fleet will automatically move
your service instances across your CoreOS cluster as hosts appear
and go down.

Rather than creating service files for fleet manually, this controller
will do it for you. It might also create a sidecar file for each of 
your containers for service discovery.
 

Flynn-Host
----------

The Layer 0 of Flynn can do similar things as fleet, but doesn't depend
on CoreOS.


Service Discovery
=================

Ultimately, the challenge presented by service discovery isn't directly
within the scope of a controller like this, since it is about services
communicating with each other.

However, there are some ways in which you will find the involvement of
the controller helpful:

- It will be able to inject environment variables into services so that 
  the service discovery system can be found.

- Plugins can create sidecar files or services, inject tools to interact
  with service discovery into containers etc.
  
- Certain services the controller provides will  need to interact with 
  service discovery. For example, the ``gitreceive`` plugin needs to find
  the controller.


Currently, there is a service discovery plugin using ``discoverd`` and 
``etcd``, though it is not hard to support any type of system.


Getting started
---------------

(add setup instructions)



Describing regular services
---------------------------

(explain how a docker service is written in YAML, and global environment vars)


12-factor apps
--------------

(introduce the "app" plugin).


Using service discovery
-----------------------

(introduce discoverd based service discovery plugins)


Initializing databases
----------------------

(deal with the problem of setting up a database initially)


Deploy by template plugin
-------------------------

Its premise is that you define the set of services that together make up
an application in a template, and you can then "roll out" one or multiple
instances of the app (say production and staging).
 
 
Rather than communicating all pieces of configuration individually to the
controller ala "heroku config:add", the service configuration is described
in a YAML file.

Design goals include:

- For the templates to not become stale, they need to be the primary method
  of deploying changes. The files and the process needs to be simple.

- The template only specifies the abstract service configuration, not
  the infrastructure configuration (how many instances to scale to, on
  which hosts to run them).

- Enforce the use of service discovery. Each service is a self-contained
  unit that can be treated without worrying about its dependencies. Make 
  the rigorous use of service discovery as simple as possible.


Describing your infrastructure
==============================

(functionality that breaks out of the "define a web app in an re-usable way",
 concept, like mapping a particular domain to a particular instance of the
 app)


Routing domains
---------------

When you run an application, whether it is a custom container or via a
buildpack, you'll generally want to put it behind a reverse proxy; you'll be
able to run multiple instances of your app, on multiple hosts, and have the
proxy redirect requests to them.

There is currently one plugin for the ``strowger`` router, which works with
the ``discoverd`` service discovery system. Define your domains in a global
section, like this:

    Domains:
        example.org
            http: example:app
        staging.example.org
            http: example-staging:app
            auth: {'internal': 'secret'}

We run two deployments here, ``example`` and ``example-staging``. The
``strowger`` plugin recognizes the ``http`` key, and will tell the router
to serve the domain ``example.org`` by forwarding requests to the
``example:app`` service, which by convention should be the ``app`` service
of the ``example`` deployment.

In the staging example, we can see that it also allows an ``auth`` option,
which will enforce HTTP Digest authentication.

