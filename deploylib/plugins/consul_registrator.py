"""
post start of instance:
    register all ports with consul

post stop of instance:
    remove all ports from consul

postprocess service (before start service):
    add registrator env vars

    add ambassadord env vars, link
"""


"""Uses consul/registrator/ambassadord for service discovery.

Expects ambassadord, registrator consul to run as a host service
(on every host). There is a bootstrap script. This will simply provide the
correct environment variables to the containers to match everything up.

This service discovery mode currently has the problem that broken services
might not get removed:

- When registrator is missing a stop event due to not running temporarily
- In particular when in that time a new version of the service is started
  with a new id; then the old one will not even be overwritten with the
  new service address once registrator comes back.

There are some options we have for solving this:

1. Rather than consul, use a backend with a real TTL mode, i.e. etcd, and
   then let registrator use TTL and refresh; requires registrator to run,
   or all services will be unregistered.

2. Continue with consul, but make registrator send TTL health checks
   (https://github.com/gliderlabs/registrator/issues/154). Same as (1),
   though instead of removing problematic services, as a real TTL may do,
   they may stay in the catalog marked as dead.

3. Configure real health checks. This clearly is the best option, does not
   require registrator to run, and is even incompatible with TTL expiry.

4. Make the controller deregister (possibly even register) services with
   consul initially on start/stop. Now the controller keeps the catalog
   clean, and registrator keeps it up to date with running/not running state.
   If we combine this with health checks, indeed we do not need registrator.
"""

import consul
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin


class RegistratorAmbassadorConsul(Plugin):
    """
    Using the progrium/registrator image for service discovery,
    and ambassadord for consumption

    This adds the environment variables to the containers for proper naming.
    """

    def _ports_from_service(self, instance):
        defined_ports = instance.version.definition['ports']
        for port_name, container_port in defined_ports.items():
            yield port_name

    def _get_name_for_port(self, service, portname):
        if portname:
            return '%s-%s' % (service.full_name, portname)
        else:
            return service.full_name

    def _get_service_id_for_port(self, service_id, portname):
        if isinstance(service_id, tuple):
            service_id = service_id[1]  # backwards compat hack, remove soon
        service_id_base = 'hafez:%s' % service_id
        if portname:
            return '%s:%s' % (service_id_base, portname)
        else:
            return service_id_base

    def post_start(self, service, instance, port_assignments):
        """Add instances for all services (all ports) to consul catalog.
        """
        c = consul.Consul(ctx.cintf.get_host_ip())
        for portname in self._ports_from_service(instance):
            name = self._get_name_for_port(service, portname)
            id = self._get_service_id_for_port(instance.id, portname)
            print "Adding service to consul catalog: %s, id=%s" % (name, id)
            c.agent.service.register(
                name, service_id=id, port=port_assignments[portname]['host'])

    def post_stop(self, service, instance):
        """Remove all services for this instance fro consul
        """
        c = consul.Consul(ctx.cintf.get_host_ip())
        for portname in self._ports_from_service(instance):
            name = self._get_name_for_port(service, portname)
            id = self._get_service_id_for_port(instance.id, portname)
            print "Removing service from consul catalog: %s" % id
            c.agent.service.deregister(service_id=id)

    def before_start(self, service, definition, runcfg, port_assignments):
        deploy_id = service.deployment.id

        # I imagined this as a default, but registrator seems to ignore the
        # port-specific instructions if it finds this.
        # runcfg['env'].update({
        #     'SERVICE_NAME': service_name_base,
        #     'SERVICE_ID': service_id
        # })

        for pname, map in port_assignments.items():
            if not map['host']:
                continue

            # deploy:service:port or deploy:service for the
            # default port, indicated by an empty string.
            register_name = self._get_name_for_port(service, pname)
            register_id = self._get_service_id_for_port(runcfg['name'], pname)

            runcfg['env'].update({
                'SERVICE_%s_NAME' % map['container']: register_name,
                'SERVICE_%s_ID' % map['container']: register_id
            })

        # Use ambassadord backend to expose the services
        count = 0
        for env_var, service_name in definition['kwargs'].get('expose', {}).items():
            port = 10000 + count
            runcfg.setdefault('links', {})
            runcfg['links']['backends'] = 'backends'
            runcfg['env'][env_var] = 'backends:%s' % port
            runcfg['env']['BACKEND_%s' % port] = '%s-%s.service.consul' % (deploy_id, service_name)

            count += 1


