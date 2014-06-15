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

(talk about plugins that can set up domain routing). 
