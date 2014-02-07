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

"""
============
 Pyheapdump
============

Create and debug heap dumps.

.. warning::
   This is alpha quality code.

.. note::
   The pyheapdump package currently requires Python 2.7.

.. autofunction:: create_dump

.. autofunction:: save_dump

.. autofunction:: load_dump

.. autofunction:: debug_dump

"""

from __future__ import absolute_import, print_function, unicode_literals, division
from ._pyheapdump import *
