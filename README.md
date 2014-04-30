This is me trying to use docker.

What I want
-----------

The key goal is to layout all the individual services an app requires in
a YAML template, then deploy this template one, or multiple times (say
live and staging).

The template isn't concerned with the runtime configuration (like in
maestro-ng). It doesn't know anything about servers or scaling settings.
Conceptually, you'd interact directly with your cluster to make these
types of changes.

But changes to the service configuration itself should be made through
re-applying a new version of the template - or it would become stale.
Updating the template needs to be the best and easiest way to change a
deployed set of services.


What it is right now
--------------------

It is *very much* a work in progress.

- There is a controller your supposed to run on you your host
  (I want to support multiple hosts later). It has a HTTP API.
- There is a command line client reading the YAML templates.
- The controller will use the Docker API to start containers.
- Once a container is started, that is it. No monitoring etc.
- The controller remembers a list of deployed applications and the
  container ids of their services, so a template sync can replace them.


What might happen in the future
-------------------------------

I care about the template part, and don't care about re-implementing
the PaaS part. In the future the controller might:

- Write out CoreOS fleet service files.
- Use flynn-host to start services across a cluster, and act like a scheduler.
- Go away, and the client might talk to flynn-controller directly.

I'd also like to go one level up and define the actual deployed applications
in a template, along with runtime data like domains being routed to the app
or the backup options. This is to combine a system documentation with a tool
to easily setup things like DNS and backups.


My goals here
-------------


1. I want the language to describe containers to be at least as or easier
   than running containers manually.

2. Once I've layed out the services required for an app, I want to be able
   to easily run multiple instances of it (a staging version, or instances
   for different customers).

3. There need to be facilities to work with an existing instance, i.e.
   deploy a new version of the app or service.

4. Base everything on service discovery rather than links. Running a container
   with etcd is not hard, and by providing the right tools, doing this right
   should not entail extra hardship (not there yet).
