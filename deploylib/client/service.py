from collections import OrderedDict
from os.path import join as path, dirname, normpath
import yaml


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
    def load(cls, filename, plugin_runner=None):
        with open(filename, 'r') as f:
            structure = yaml.load(f)

        # All keys in the template fall in one of two categories:
        # A container to run, or an arbitrary section of global data.
        global_data = {}
        services = OrderedDict()
        for name, item in structure.items():
            # Uppercase idents are non-service types
            if name[0].isupper():
                global_data.update({name: item})
                continue
            # Otherwise, it is a service
            services[name] = Service(item)
            services[name].filename = filename

        # Run plugins to post-process the loaded file. Used because
        # for globals, this is the only place where the base filename
        # is known such that relative paths can be resolved. The alternative
        # would be making the merging/loading more intelligent, such that
        # Apps: can be loaded into "smart" objects like services
        # themselves already are.
        if plugin_runner:
            plugin_runner('file_loaded', services, global_data, filename=filename)

        # Resolve includes
        for include_path in global_data.get('Includes', []):
            included_sf = ServiceFile.load(include_path)

            # Merge one level deep
            merged_data = included_sf.globals
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
        servicefile.globals = global_data
        servicefile.services = services

        return servicefile
