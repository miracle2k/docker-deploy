#!/usr/bin/env python
# coding: utf-8

from setuptools import setup, find_packages


setup(
    name='deployd',
    url='https://github.com/miracle2k/docker-deploy',
    version='0.1',
    license='BSD',
    author=u'Michael Elsdörfer',
    author_email='michael@elsdoerfer.com',
    description=
        'work in progress docker deployment scripts',
    packages=find_packages(),
    package_data={'': ['Bootstrap']},
    install_requires=[
        'docopt>=0.6.1',
        'flask>=0.10',
        'netifaces>=0.10',
    ],
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    entry_points="""
[console_scripts]
deployd = deploylib.daemon:run
calzion = deploylib.client:run
""",
)
