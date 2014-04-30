from os.path import join as path, dirname, normpath
import yaml
from .utils import OrderedDictYAMLLoader


class Service(dict):
    """Local service representation. Knows the location of the file the
    definition was read from.
    """
    filename = None
    def path(self, rel):
        return normpath(path(dirname(self.filename), rel))


class ServiceFile(object):
    """A file listing multiple services.

    We enforce service discovery usage, so the order of the services
    in the file does not matter, nor are there any other relations
    between them.

    However, the file does support global values that need to be merged
    into the service definitions.
    """

    @classmethod
    def load(cls, filename):
        with open(filename, 'r') as f:
            # Services should generally not depend on a specific order,
            # instead rely on service discovery.
            # There is one exception though: When deploying an initial
            # template, a database might need to be initialized first
            # to setup a user account, before that user account can be
            # added to another containers environment.
            # TODO: Do we really need this? Starting discoverd before shelf?
            opts={'Loader': OrderedDictYAMLLoader}
            structure = yaml.load(f, **opts)

        # All keys in the template fall in one of two categories:
        # A container to run, or an arbitrary section of global data.
        global_data = {}
        services = {}

        for name, item in structure.items():
            # Uppercase idents are non-service types
            if name[0].isupper():
                global_data.update({name: item})
                continue
            # Otherwise, it is a service
            services[name] = Service(item)
            services[name].filename = filename

        # Resolve includes
        for include_path in global_data.get('Includes', []):
            included_sf = ServiceFile.load(include_path)

            # Merge one level deep
            merged_data = included_sf.data
            for key, value in global_data.items():
                if isinstance(value, dict):
                    merged_data.setdefault(key, {})
                    merged_data[key].update(value)
                # TODO: lists
                else:
                    merged_data[key] = value
            global_data = merged_data

            # Also merge services
            merged_services = included_sf.services
            merged_services.update(services)
            services = merged_services

        servicefile = cls()
        servicefile.filename = filename
        servicefile.data = global_data
        servicefile.services = services

        return servicefile
