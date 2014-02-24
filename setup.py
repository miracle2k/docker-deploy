#!/usr/bin/env python
# coding: utf-8

from setuptools import setup


setup(
    name='docker-deploy',
    url='https://github.com/miracle2k/docker-deploy',
    version='1.0',
    license='BSD',
    author=u'Michael Elsdörfer',
    author_email='michael@elsdoerfer.com',
    description=
        'work in progress docker deployment scripts',
    py_modules=['deploylib'],
    scripts=['deploy.py'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
    entry_points="""[console_scripts]\nshelvedump = shelvedump:run\n""",
)