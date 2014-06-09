"""A collection of plugins that make up the Upstart backend.

This includes the actual backend implementation, but also plugins that
write upstart files for the system services, and upstart files to control
a whole deployment at once.

That is, you'll be able to say::

    initctl start my-deployment

And all the service instances within that deployment will come up.

The specific dependencies look like the following:

<- means "on starting" / before
-> means "on start"/ after

For start::

             -- boot
             |
    root <- etcd -> discoverd
      |                    -> shelf     -> root
      |                    -> strowger  -> root
      -> a deployment -> all deployment services

For stop::

    root <-> etcd -> discoverd -> deployment -> all deployment services
                      |
            shelf  <-------> strowger
"""

import os
from deploylib.daemon.backend import DockerOnlyBackend
from deploylib.plugins import Plugin


def write_upstart_conf(name, template, **kwargs):
    filename = os.path.join(
        os.environ.get('UPSTART_DIR', '/etc/init'), name + '.conf')
    with open(filename, 'w') as f:
        f.write(template.format(name=name, **kwargs))


class UpstartBackend(DockerOnlyBackend):
    """Create upstart files along with docker containers.
    """

    def start(self, service, runcfg, instance_id):
        self.write_upstart_for_service(service.deployment, runcfg)
        return DockerOnlyBackend.start(self, service, runcfg, instance_id)

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

    def on_system_init(self):
        # Run etcd on boot, or when the control root service starts.
        etcd = """
description "{name}"
start (on filesystem and started docker) or starting docker-deploy
stop on runlevel [!2345] or stopping etcd
respawn
script
  /usr/bin/docker start -a {name}
end script
"""
        write_upstart_conf('etcd', etcd)

        def_template = """
description "{name}"
start on started {dep}
stop on stopping {dep}
respawn
script
  /usr/bin/docker start -a {name}
end script
"""
        # etcd causes discoverd
        write_upstart_conf('discoverd', def_template, dep='etcd')
        # discoverd causes shelf and strowger
        write_upstart_conf('shelf', def_template, dep='discoverd')
        write_upstart_conf('strowger', def_template, dep='discoverd')

        # Finally, create an abstract service file to control the whole
        # system at once. etcd causes itself to start before this, and
        # the root considers itself started when shelf and strowger
        # finally run.
        #
        # This means it has the following use cases:
        #   - When this service emits starts, we know the base system is ready.
        #   - When we start or stop this, we bring the whole system up or down.
        root = """
description "docker-deploy"
start on (started shelf and started strowger)
stop on stopped etcd
"""
        write_upstart_conf('docker-deploy', root)

    def on_create_deployment(self, deployment):
        """This is an abstract service that is used as a "start on"
        "stop on" hook for every service in this deployment.
        """
        template = """
description "{name}"
author "docker-deploy"
start on started docker-deploy
stop on stopping docker-deploy
        """
        write_upstart_conf(deployment.id, template)



