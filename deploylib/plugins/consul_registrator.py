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

from deploylib.plugins import Plugin


# XXX run via service definition
#


class RegistratorAmbassadorConsul(Plugin):
    """
    Using the progrium/registrator image for service discovery,
    and ambassadord for consumption

    This adds the environment variables to the containers for proper naming.
    """

    def before_start(self, service, definition, runcfg, port_assignments):
        deploy_id = service.deployment.id

        service_name_base = '{did}-{sname}'.format(did=deploy_id, sname=service.name)
        service_id_base = 'hafez:%s' % runcfg['name']

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
            if pname:
                register_name = '%s-%s' % (service_name_base, pname)
                register_id = '%s:%s' % (service_id_base, pname)
            else:
                register_name = service_name_base
                register_id = service_id_base

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


