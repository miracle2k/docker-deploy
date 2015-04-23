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
"""

import os
import docker
import docker.errors
from os import path


class Backend(object):
    """A backend provides the following operations:

    prepare(runcfg)
        A optional method called before start() that basically allows
        the backend to fail early, before the caller might start to
        shutdown any existing instances they might want to replace.

    start(runcfg) -> instance id
        Spin up an instance of the thing in runcfg.

    status(instance id)
        Is the instance up or down.

    terminate(instance id)
        Remove the instance.

    once(runcfg) - Streaming output
        Run a one-time command.

    This design is flexible enough to allow a supervisor based backend to
    choose whether a service instance should be kept up by way of
    restarting the same container (i.e. an instance is mapped to a single
    docker container), or by using 'docker run' to create a new container
    every time the instance comes up.
    """

    def prepare(self, runcfg, service):
        pass

    def start(self, runcfg, service, instance_id=None):
        raise NotImplementedError()

    def terminate(self, instance_id):
        raise NotImplementedError()

    def status(self, instance_id):
        raise NotImplementedError()

    def once(self, runcfg):
        raise NotImplementedError()


class DockerOnlyBackend(object):
    """Simply uses the docker API to create containers and start them.

    The problem with this is that Docker's -restart functionality cannot
    be trusted; Services regularly do not come up after a host reboot.
    That seems to be related to exit codes somehow.
    """

    def __init__(self, docker_url):
        self.client = docker.Client(
            base_url=docker_url, version='1.6', timeout=10)

    def prepare(self, runcfg, service):
        cid = self.create_container(runcfg)

        # Make sure the volumes exist
        for host_path in runcfg['volumes'].keys():
            if not path.exists(host_path):
                os.makedirs(host_path)

        return cid

    def start(self, runcfg, service, instance_id):
        self.client.start(
            runcfg['name'],
            binds=runcfg['volumes'],
            port_bindings=runcfg['ports'],
            links=runcfg.get('links', {}),
            privileged=runcfg['privileged'])
        return instance_id, runcfg['name']

    def terminate(self, (instance_id, name)):
        try:
            self.client.stop(instance_id, 10)
        except:
            pass

    def once(self, runcfg):
        container = self.create_container(runcfg)
        self.client.start(
            container,
            binds=runcfg['volumes'],
            port_bindings=runcfg['ports'],
            links=runcfg.get('links', {}),
            privileged=runcfg['privileged'])
        return self.client.wait(container)

    def pull_image(self, imgname):
        try:
            self.client.inspect_image(imgname)
        except docker.errors.APIError:
            print "Pulling image %s" % imgname
            print self.client.pull(imgname)

    def create_container(self, runcfg):
        # If the given name already exists, we need to delete the container
        # first, otherwise, we'll definitely fail.
        if runcfg.get('name'):
            try:
                self.client.inspect_container(runcfg['name'])
            except docker.errors.APIError:
                pass
            else:
                print "Removing existing container %s" % runcfg['name']
                self.client.kill(runcfg['name'])
                self.client.remove_container(runcfg['name'])

        # If the image does not exist yet, pull it
        self.pull_image(runcfg['image'])

        # Create the container
        print "Creating container %s" % runcfg.get('name', '(unnamed)')
        result = self.client.create_container(
            image=runcfg['image'],
            name=runcfg.get('name'),
            entrypoint=runcfg['entrypoint'],
            command=runcfg['cmd'],
            environment=runcfg['env'],
            # Seems needs to be pre-declared (or in the image itself)
            # or the binds won't work during start.
            ports=runcfg['ports'].keys(),
            volumes=runcfg['volumes'].values(),
        )
        container_id = result['Id']
        return container_id
