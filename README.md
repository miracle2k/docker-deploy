This is slowly becoming a usable docker-based deployment tool. 

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
  
  
Implementing the concept
------------------------

Your template for your web app using a Postgres database and a redis cache
might look like this:
 
    mycompany/redis:
    mycompany/postgres:
    my-webapp:
        git: .
        

Via ``./calzion deploy template.yaml myapp-staging``, this template would 
simply be converted into the following API calls to a controller which
needs to run only once for a cluster:
    
    create_deployment('myapp-staging')
    set_service('myapp-staging, 'mycomp/redis',  {})    
    set_service('myapp-staging, 'mycomp/web',  {'git': '.'})
    set_service('myapp-staging, 'mycomp/postgres',  {})
    

Notice the ``set_service()`` calls are separate, and their order is 
irrelevant.

The controller starts the redis and postgres containers (on a random host
by default). The special ``git`` key triggers a plugin that is responsible
to support 12-factor style apps. The plugin might do the following:

- Setup a git repository to push to for deployments.
- Ask the client to upload the code.

Once the application code has been provided, it can use ``flynn/slugbuilder``
and ``flynn/slugrunner`` to deploy it as a docker container.

The containers find each other because they have all registered with a 
service discovery system, based on receiving the deployment name 
``myapp-staging`` as an environment variable.

The controller is written in Python, and can run in a container itself
(convenient everywhere, necessary for i.e. CoreOS).
  
  
The current state
-----------------

This is still very much a work in progress, but it is getting to a point
where it might be usable.

Currently:

- Only works with a single host.
- Has dependencies to a number of Flynn components hardcoded (etcd,
  discoverd, strowger). There is no reason why this has to remain so.

Since I care about the deploy-via-template part, and not so much about
re-implementing a PaaS system, I'd rather defer the job of running the
containers and keeping them up to a backend.

Currently the controller creates the containers via the Docker API and writes
upstart service files for them, but in the future, it might also support
things like CoreOS fleet, or use flynn-host. 


Getting started
---------------

(add setup instructions)



Describing regular services
---------------------------

(explain how a docker service is written in YAML, and global environment vars)


Ports
~~~~~

Ports are the endpoints that a service exposes. They are defined somewhat
differently than what you may be used to: You have to name them for clarity:
    
    elsdoerfer/rethinkdb:
        ports: {driver: 28015, cluster: 29015, web: 8080}

Here the container is telling the controller on which ports it's services 
can be found. Each port you define in this way will be mapped to your 
cluster's local network (for now this means the host docker0 interface).
 
These host-mapped port are than automatically registered with service
discovery.
 
Alternatively, a service may want to be told by the controller
where it should expose itself::

    elsdoerfer/rethinkdb:
        cmd: rethinkdb --driver-port $PORT_DRIVER ...
        ports: driver, cluster, web
                
The controller will insert environment variables in the form of
``PORT_{name}`` to tell the service where it will be looked for.

**Note**: The above is a short-hand version of:

    elsdoerfer/rethinkdb:
        ports: {driver: assign, cluster: assign, web: assign}
        
If you do not define a port, there is always a single default port, given
as the environment variable ``PORT``.

WAN Ports
~~~~~~~~~

The networking concept defines the idea of a local port (the way services
within a cluster access each other - this is the docker0-mapped port above),
and a WAN port, which is for services like a http proxy which need to
accessible from the outside. Define WAN ports this way:

    elsdoerfer/strowger:
        ports: [http, api]
        wan_map: {":80": http}

         
LAN and WAN are concepts. There are different ways to implement these
concepts:

- The plugin `host_lan` maps all LAN ports to an interface on the host.
  This interface may be ``docker0`` for a single host cluster, or a custom
  LAN interface that you have made available within your cluster. You could
  also use the WAN interface of your host, and use firewall rules, or simply
  authentication to protect your LAN services. 
  
- A `container_lan` plugin could ask all services to bind their ports to a
  LAN interface that is available in containers. They could then be
  addressed using the container IP address.

In both cases, WAN ports are mapped to the host WAN interface.

Other plugins could use ambassador containers or firewall rules to
implement these concepts.


12-factor apps
--------------

(introduce the "app" plugin).


Using service discovery
-----------------------

(introduce discoverd based service discovery plugins)


Initializing databases
----------------------

(deal with the problem of setting up a database initially)


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

