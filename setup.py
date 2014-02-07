#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 by Anselm Kruis
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#


from setuptools import setup
import sys
if sys.version_info < (2, 7):
    print 'ERROR: pyheapdump requires at least Python 2.7 to run.'
    sys.exit(1)

for line in open('conf.py'):
    if line.startswith('release = '):
        exec(line)
        break

setup(
    name='pyheapdump',
    version=release,
    description='Post-mortem debugging for Python programs',
    author='Anselm Kruis',
    author_email='a.kruis@science-computing.de',
    url='http://pypi.python.org/pypi/pyheapdump',
    packages=['pyheapdump'],

    # don't forget to add these files to MANIFEST.in too
    #package_data={'pyheapdump': ['examples/*.py']},

    long_description="""
pyheapdump is a Post-Mortem debugging extension
-----------------------------------------------

Pyheapdump allows post-mortem debugging for Python programs.

It writes all relevant objects into a file and can later load
it in a Python debugger.

Works best with Pydevd but also with the built-in pdb and with
other popular debuggers.

This version requires Python 2.7. Unfortunately, there is currently no
Python 3 version.

Git repository: git://github.com/akruis/pyheapdump.git
""",
    classifiers=[
                 "License :: OSI Approved :: Apache Software License",
                 "Programming Language :: Python :: 2.7",
                 "Programming Language :: Python :: Implementation :: CPython",
                 "Programming Language :: Python :: Implementation :: Stackless",
                 "Environment :: Console",
                 "Operating System :: OS Independent",
                 "Development Status :: 3 - Alpha",  # hasn't been tested outside of flowGuide2
                 "Intended Audience :: Developers",
                 "Topic :: Software Development :: Libraries :: Python Modules",
                 'Topic :: Software Development :: Debuggers',
      ],
      keywords='pickling sPickle pickle stackless post-mortem debug debugger',
      license='Apache Software License',
      install_requires=[
        'sPickle>=0.1.4',
      ],
      platforms="any",
      test_suite="pyheapdump",
    )
