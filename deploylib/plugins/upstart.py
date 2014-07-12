"""This is designed to run services using upstart, mostly intended for
a single-host setup.

Services will hook themselves as "start on docker-deploy", so when your
base system is ready, raise this event.

Apart from creating an upstart file for each service, it also creates one
for each deployment. That is, you'll be able to say::

    initctl start my-deployment

And all the service instances within that deployment will come up.
"""

import os
from subprocess import check_output, CalledProcessError
from deploylib.daemon.backend import DockerOnlyBackend
from deploylib.plugins import Plugin


def write_upstart_conf(name, template, **kwargs):
    filename = os.path.join(
        os.environ.get('UPSTART_DIR', '/etc/init'), name + '.conf')
    with open(filename, 'w') as f:
        f.write(template.format(name=name, **kwargs))


def rm_upstart_conf(name):
    filename = os.path.join(
        os.environ.get('UPSTART_DIR', '/etc/init'), name + '.conf')
    if os.path.exists(filename):
        os.unlink(filename)


class UpstartBackend(DockerOnlyBackend):
    """Create upstart files along with docker containers.
    """

    def start(self, runcfg, service, instance_id):
        # First start the container manually via docker; this acts as
        # validation; if it fails, don't bother writing the initscript.
        result = DockerOnlyBackend.start(self, runcfg, service, instance_id)

        # Create an upstart initscript for the service.
        self.write_upstart_for_service(service.deployment, runcfg)

        # Ask upstart to start the service; it will attach to the
        # manually started container.
        check_output('initctl start %s' % runcfg['name'], shell=True)

        return result

    def terminate(self, (instance_id, name)):
        # First, stop the service; removing the initscript is not enough
        # it seems to stop it from restarting.
        try:
            output = check_output('initctl stop %s' % name, shell=True)
        except CalledProcessError:
            # It is entirely possible the service is not running currently.
            pass
        else:
            # If the service is not running, "initctl stop" will return
            # a failure, so skip the call in that case.
            if not 'stop/waiting' in output:
                check_output('initctl stop %s' % name, shell=True)

        # Finally  remove the service file.
        rm_upstart_conf(name)

    def write_upstart_for_service(self, deployment, runcfg):
        # Upstart file for an individual service. Linked to start
        # alongside abstract service for the whole deployment.
        template = \
"""
description "{name}"
author "docker-deploy"
start on starting {deployment}
stop on stopping {deployment}
respawn
script
  /usr/bin/docker start -a {name}
end script
"""
        write_upstart_conf(runcfg['name'], template, deployment=deployment.id)


class UpstartPlugin(Plugin):

    def on_create_deployment(self, deployment):
        """This is an abstract service that is used as a "start on"
        "stop on" hook for every service in this deployment.
        """
        if not deployment.id:
            # The system deployment.
            return
        template = """
description "{name}"
author "docker-deploy"
start on started docker-deploy
stop on stopping docker-deploy
        """
        write_upstart_conf(deployment.id, template)



