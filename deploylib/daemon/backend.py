"""While I am still deciding which direction this should go in, the backends
represent the most low-level abstraction dealing with containers.

The user's service definition (with its variables and inherited environment
variables) are converted to a flat ``runcfg``, which is essentially the final
docker configuration of a container.

The backend implementation takes the runcfg and, as the final link that we
have to docker, makes sure these containers get started.

Possible backends that I can imagine right now are:

- Pass runcfg as a job to flynn-host
- Pass runcfg as a job to flynn-controller (we might not have to manage
     multiple different hosts ourselves).
- Create CoreOS fleet service files, and invoke those.



FLYNN-HOST implementation
        FLYNN-CONTROLLER implementation (each host uses a segment of the same flyn-controller)
        FLEET implementation (all host instances write to the local init dir, but represent
                              different actual hosts to run services on)
           on-create: make fleetfile
           on-start: invoke fleet

        INITD implementation (single-host only)
           on-create: create container + initd file
             pull + create + create file
             ----> at this point we have created the version
           on-start: start container manually
             ----> before run, shut down old containers
"""
import os
import docker
from os import path


class DockerOnlyBackend(object):
    """Simply uses the docker API to create containers and start them.

    The problem with this is that Docker's -restart functionality cannot
    be trusted; Services regularly do not come up after a host reboot.
    That seems to be related to exit codes somehow.
    """

    def __init__(self, docker_url):
        self.client = docker.Client(
            base_url=docker_url, version='1.6', timeout=10)

    def create(self, runcfg):
        return self.create_container(runcfg)

    def start(self, runcfg):
        # Make sure the volumes exist
        for host_path in runcfg['volumes'].keys():
            if not path.exists(host_path):
                os.makedirs(host_path)

        print "Starting container %s" % runcfg['name']
        self.client.start(
            runcfg['name'],
            binds=runcfg['volumes'],
            port_bindings=runcfg['ports'],
            privileged=runcfg['privileged'])

    def stop(self, container_id):
        try:
            self.client.stop(container_id, 10)
        except:
            pass

    def create_container(self, runcfg):
        # If the given name already exists, we need to delete the container
        # first, otherwise, we'll definitely fail.
        try:
            self.client.inspect_container(runcfg['name'])
        except docker.APIError:
            pass
        else:
            print "Removing existing container %s" % runcfg['name']
            self.client.kill(runcfg['name'])
            self.client.remove_container(runcfg['name'])

        # If the image does not exist yet, pull it
        print "Pulling image %s" % runcfg['image']
        print self.client.pull(runcfg['image'])

        # Create the container
        print "Creating container %s" % runcfg['name']
        result = self.client.create_container(
            image=runcfg['image'],
            name=runcfg['name'],
            entrypoint=runcfg['entrypoint'],
            command=runcfg['cmd'],
            environment=runcfg['env'],
            # Seems need to be pre-declared (or or in the image itself)
            # or the binds won't work during start.
            ports=runcfg['ports'].keys(),
            volumes=runcfg['volumes'].values(),
        )
        container_id = result['Id']
        return container_id
