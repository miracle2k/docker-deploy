from . import Plugin


class DomainPlugin(Plugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the strowger router.
    """

    def post_deploy(self, servicefile):
        domains = servicefile.data.get('Domains', {})
        if not domains:
            return

        rpc_ip = self.host.discover('flynn-strowger-rpc')

        for domain, data in domains.items():
            cert = key = None
            if 'cert' in data:
                cert = open(servicefile.path(data['cert']), 'r').read()
                key_paths = [servicefile.path(data['key'])]
                if 'KEY_PATH' in os.environ:
                    key_paths.append(path(os.environ['KEY_PATH'], data['key']))
                for candidate in key_paths:
                    if exists(candidate):
                        key = open(candidate, 'r').read()
                if not key:
                    raise ValueError('key not found in: %s' % key_paths)

            self.host.e(run,
                'strowger-rpc -rpc {rpc} {ssh} {domain} {sname}'.format(
                    rpc=rpc_ip,
                    ssh='-cert "{cert}" -key "{key}"'.format(cert=cert, key=key) if cert else '',
                    domain=domain,
                    sname=data['service-name']
                ))

        # TODO: Support further plugins to configure the domain DNS