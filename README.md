Scripts I use for deploying docker.

This is pretty rough for now. I define containers in YAML files and deploy
them by executing commands remotely via ssh. In the future, I'd like to
evolve this to use even more of Flynn's infrastructure, like the host and
scheduling services (it already uses discoverd and the strowger router).

The fundamental difference to meastro-ng is that the actual host container
state is not serialized in the YAML file. The YAML files do not layout the
host cluster; instead, they act like templates. Once you deploy a template
to a host (in the future maybe a cluster of hosts), the host itself holds
the state (currently, a bunch of files are created for this). The system
will then interact directly with the host cluster to manage the running
services.


There were a couple of design goals here for me:

1. I want the language to describe containers to be at least as or easier
   than running containers manually.

2. Once I'e layout out the services required for an app, I want to be able
   to easily run multiple instances of it (a staging version, or instances
   for different customers).

3. There need to be facilities to work with an existing instance, i.e.
   deploy a new version of the app or service.

4. Base everything on service discovery rather than links. Running a container
   with etcd is not hard, and we might just as well do this right.

5. Scaling is not an immediate concern, and indeed currently only once
   instance of each service is supported. In the future, the Flynn
   infrastructure might help adding scaling features.

