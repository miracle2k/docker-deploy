import contextlib
import json
import os
from os.path import join as path, dirname, abspath, exists
import random
import tempfile
import uuid
import io
import yaml
from .utils import OrderedDictYAMLLoader


class Service(dict):

    def __init__(self, name, data):
        # Shortcut specifies only the command
        if isinstance(data, basestring):
            data = {'cmd': data}

        data.setdefault('volumes', [])
        data.setdefault('cmd', '')
        data.setdefault('entrypoint', '')
        data.setdefault('env', {})
        data.setdefault('ports', {})

        dict.__init__(self, data)

        # Image can be given instead of an explicit name. The last
        # part of the image will be used as the name only.
        self['name'] = name
        if not 'image' in self:
            self['image'] = name
            self['name'] = name.split('/')[-1]

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)

    @property
    def ports(self):
        """Ways to specify ports:

        NAME: EXPOSURE
            Provider to container a random mapped port named NAME.

        PORT : EXPOSURE
            Map the specified local PORT to the same host port.

        PORT : PORT
            Map the specified local PORT to the specified host port.

        NAME : PORT
            Illegal.

        (TODO: Needs reworking: What if I want to specify an exposure
        for a PORT:PORT mapping? The strowger bootstrapped service
        is an example of this actually)

        Exposure values for ports are:

        - wan: Map to public host ip.
        - host: Map to docker0 interface.
        """
        ports = self['ports']
        # If a list is specified, assume "host" for all.
        if isinstance(ports, list):
            return {p: 'host' for p in ports}
        return ports


class ServiceFile(object):
    """A file listing multiple services."""

    @classmethod
    def load(cls, filename):
        with open(filename, 'r') as f:
            # Services should generally not depend on a specific order,
            # instead rely on service discovery.
            # There is one exception though: When deploying an initial
            # template, a database might need to be initialized first
            # to setup a user account, before that user account can be
            # added to another containers environment.
            opts={'Loader': OrderedDictYAMLLoader}
            structure = yaml.load(f, **opts)

        servicefile = cls()
        servicefile.filename = filename
        for name, service in structure.items():
            if name == '?':
                # Special id gives the name
                servicefile.name = name
                continue
            if name[0].isupper():
                # Uppercase idents are non-service types
                servicefile.data.update({name: service})
                continue
            service = Service(name, service)
            service.from_file = servicefile
            servicefile.services.append(service)

        # Resolve includes:
        for include in servicefile.data.get('Includes', []):
            sf = ServiceFile.load(include)
            sf.from_file = servicefile
            new_data = sf.data
            # Merge one level deep
            for key, value in servicefile.data.items():
                if isinstance(value, dict):
                    new_data.setdefault(key, {})
                    new_data[key].update(value)
                # TODO: lists
                else:
                    new_data[key] = value
            servicefile.data = new_data
            servicefile.services.extend(sf.services)

        return servicefile

    def __init__(self, name=None, services=None, other_data=None):
        self.data = other_data or {}
        self.name = name
        self.services = services or []
        self.from_file = None

    def path(self, p):
        """Make the given path absolute."""
        return abspath(path(dirname(self.filename), p))

    def __getitem__(self, item):
        return self.data[item]

    @property
    def root(self):
        """If a service file was included, this finds the root."""
        sf = self
        while sf.from_file:
            sf = sf.from_file
        return sf

    @property
    def env(self):
        return self.root.data.get('Env') or {}