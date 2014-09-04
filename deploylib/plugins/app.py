"""Runs 12-factor apps from git using flynn/slugrunner.

Will automatically install flynn/shelf as part of tye system deployment to
store compiled slugs.
"""

import os
from os.path import abspath, exists, join as path
import subprocess
import ConfigParser
import tempfile

import click
from deploylib.daemon.context import ctx
from deploylib.daemon.controller import DeployError
from deploylib.plugins.shelf import ShelfPlugin
from . import Plugin, LocalPlugin


class LocalAppPlugin(LocalPlugin):
    """Base interface for a plugin that runs as part of the CLI
    on the client.
    """

    def provide_cli(self, group):
        group.add_command(app_cli)

    def provide_data(self, service, what):
        """Server says it is missing data for the given service.

        This should return a dict of files that will be uploaded.
        """
        run = subprocess.check_output
        from deploylib.client.utils import directory

        if what != 'git':
            return False

        # The given path may be a subdirectory of a repo
        # For git archive to work right we need the sub path relative
        # to the repository root.
        project_path = self.find_project_repo(service, service['git'])
        with directory(project_path):
            git_root = run('git rev-parse --show-toplevel', shell=True)
            gitsubdir = project_path[len(git_root):]

        # Determine git version
        with directory(project_path):
            app_version = run('git rev-parse HEAD', shell=True)[:10]

        # Create and push the git archive
        with directory(project_path):
            temp = tempfile.mktemp()
            run('git archive HEAD:{} > {}'.format(gitsubdir, temp), shell=True)

            return {
                'app': (temp, {'version': app_version})
            }

    def find_project_repo(self, service, rel):
        """Try to find ``rel``. Either it's relative to the service file,
        or it must be in the user's search path.
        """
        relative_to_file = service.path(rel)
        if exists(relative_to_file):
            return relative_to_file

        # If not valid as a relative path, look in the search path
        # for the app.
        try:
            searchpath = self.app.config.get('app', 'search-path', '').split(':')
        except ConfigParser.NoSectionError, ConfigParser.NoOptionError:
            searchpath = []
        for dir in searchpath:
            candidate = path(dir, rel)
            if exists(candidate):
                return candidate

        # Not found in the search path either.
        raise EnvironmentError('Cannot find app, not a relative path '
                               'and not found in search path: %s' % rel)

    def add_dir_to_search_path(self, newdir):
        app = self.app

        path = app.config.get('app', 'search-path', default='').split(':')
        if not newdir in path:
           path.append(newdir)
        app.config.set('app', 'search-path', ':'.join(path))
        app.config.save()

        return path


class AppPlugin(Plugin):
    """Will run a 12-factor style app.
    """

    priority = 50

    def setup(self, service, version):
        if not 'git' in version.definition['kwargs']:
            return False

        # If the shelf service has not yet been setup, do so now
        shelf = ctx.cintf.get_plugin(ShelfPlugin)
        if not shelf.is_setup():
            shelf.setup_shelf()

        # If this service version has no slug id attached, hold it back
        # for now and ask the client to provide the code.
        if not version.data.get('app_version_id'):
            handled = ctx.cintf.run_plugins('needs_app_code', service, version)
            if not handled:
                # Communicate to the client it may upload the data
                ctx.custom(**{'data-request': service.name, 'tag': 'git'})

            # No code has been provided yet, put service in "hold" status.
            service.hold('app code not available', version)
            return True

    def on_data_provided(self, service, files, data):
        """Client has uploaded the app code.
        """
        if not 'app' in files:
            return

        # Use the held version, or copy the latest one
        if service.held:
            version = service.held_version
        else:
            version = service.derive()
        version.data['app_version_id'] = data['app']['version']

        ctx.job('building slug for %s, version %s' % (
            service.name, data['app']['version']))

        # Build into a slug
        uploaded_file = tempfile.mktemp()
        files['app'].save(uploaded_file)
        self.build(service, version, uploaded_file)

        # Run this new version
        ctx.cintf.setup_version(service, version)

    def rewrite_service(self, service, version, definition):
        """Convert service to be run as a slugrunner.
        """
        if not 'git' in version.definition['kwargs']:
            return False

        env = self._build_env(service, version)

        # Put together a rewritten service
        definition['env'].update(env)
        definition['image'] = 'flynn/slugrunner'
        definition['cmd'] = definition['cmd'] or ['start', definition['kwargs'].get('process', 'web')]
        # For compatibility with sdutil plugin - tell it where to find the
        # binary. Note that slugrunner has support for sdutil builtin,
        # enabled by setting the SD_NAME variable. We do not use this support
        # and instead use the sdutil plugin do its thing.
        definition['kwargs'].setdefault('sdutil', {})
        definition['kwargs']['sdutil']['binary'] = 'sdutil'

    def build(self, service, version, filename):
        """Build an app using slugbuilder.

        Note: buildstep would give us a real exclusive image, rather than a
        container that presumably needs to unpack the slug every time. Maybe
        we could also commit the slugrunner container after the first run?
        """

        # Determine the url where we'll store the slug
        slug_url = self._get_slug_url(service, version.data['app_version_id'])

        # To speed up the build, use a cache
        cache_dir = ctx.cintf.cache(
            'slugbuilder', service.deployment.id, service.name)

        # Run the slugbuilder
        docker = ctx.cintf.backend.client
        ctx.log('Pulling flynn/slugbuilder')
        docker.pull('flynn/slugbuilder')
        env = self._build_env(service, version)

        # TODO: Sending data through stdin via the API isn't obvious
        # at all, so we'll fall back on the command line here for now.
        #container = docker.create_container(
        #    image='flynn/slugbuilder',
        #    stdin=filename,
        #    command=slug_url,
        #    environment=env,
        #    volumes={cache_dir: '/tmp/cache:rw'})
        builder_image = os.environ.get('SLUGBUILDER', 'flynn/slugbuilder')

        cmd = ('cat {} | docker run -u root -v {cache}:/tmp/cache:rw {env} -i -a stdin '
              '-a stdout {image} {outuri}'.format(
                filename, outuri=slug_url, cache=cache_dir,
                image=builder_image,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()])))

        build_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, bufsize=0)

        line = build_process.stdout.readline()
        while line:
            if line.startswith('\x1b'):
                # There is some type of shell code at the beginning, and
                # it somehow prevents indentation.
                line = line[4:]
            ctx.log(line.strip())
            line = build_process.stdout.readline()

        build_process.wait()
        if build_process.returncode:
            raise DeployError('the build failed with code %s' % build_process.returncode)

    def _get_slug_url(self, service, slug_name):
        # Put together an full url for a slug
        shelf_ip = ctx.cintf.discover('shelf')
        release_id = "{}/{}:{}".format(
            service.deployment.id, service.name, slug_name)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))
        return slug_url

    def _build_env(self, service, version):
        # Put together some extra environment variables we know the
        # slugrunner image expects.
        env = {
           'APP_ID': service.deployment.id,
           'SLUG_URL': self._get_slug_url(service, version.data['app_version_id'])
        }
        env.update(version.definition['env'])
        return env



################################################################################


@click.group('app')
def app_cli():
    """Manage the app plugin."""
    pass


@app_cli.command('add-search-dir')
@click.argument('dir', type=click.Path(file_okay=False, exists=True))
@click.pass_obj
def app_addsearchpath(app, dir):
    """Register a local directory that is searched for applications.
    """
    dir = abspath(dir)
    for p in app.get_plugin(LocalAppPlugin).add_dir_to_search_path(dir):
        print p
