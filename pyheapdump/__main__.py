#
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


from __future__ import absolute_import, print_function, unicode_literals, division

import argparse
import sys

from pyheapdump import debug_dump



def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description='debug a Python heap dump')
    parser.add_argument('--debugger', '-d', choices=['auto', 'pdb', 'pydevd'], default="auto", help="select the debugger, default is 'auto'")
    parser.add_argument('--debugger-dir', help='pydevd only: the directory where the debugger is installed')
    parser.add_argument('--host', help='pydevd only: the user may specify another host, if the debug server is not in the same machine')
    parser.add_argument('--port', type=int, default=5678, help='pydevd only: specifies which port to use for communicating with the server. Default is port 5678')
    parser.add_argument('--stdout', choices=['server', 'console'], default='server', help='pydevd only: pass the stdout to the debug server so that it is printed in its console or to this process console')
    parser.add_argument('--stderr', choices=['server', 'console'], default='server', help='pydevd only: pass the stderr to the debug server so that it is printed in its console or to this process console')
    parser.add_argument('dumpfile', type=argparse.FileType(mode='rb'), help="the heap dump file")

    namespace = parser.parse_args(argv)
    return debug_dump(dumpfile=namespace.dumpfile, debugger_options=vars(namespace))

if __name__ == '__main__':
    sys.exit(main())
