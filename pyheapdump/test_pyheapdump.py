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

RUN_INTERACTIVE_TESTS = False

import sys
import unittest
import sPickle
import tempfile
import os

from . import _pyheapdump


class PyheapdumpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super(PyheapdumpTest, cls).setUpClass()
        fd, name = tempfile.mkstemp(suffix="pydump")
        os.close(fd)
        cls.dump_file_name = name

    @classmethod
    def tearDownClass(cls):
        super(PyheapdumpTest, cls).tearDownClass()
        try:
            os.unlink(cls.dump_file_name)
        except IOError:
            pass

    def setUp(self):
        super(PyheapdumpTest, self).setUp()

    def tearDown(self):
        super(PyheapdumpTest, self).tearDown()

    def raise_exc(self):
        very_special_name = 4711
        return self.raise_exc1()

    def raise_exc1(self):
        another_name = id(self)
        if self is not None:
            1 / 0
        return another_name

    def testCreateDump(self):
        try:
            self.raise_exc()
        except Exception:
            p = _pyheapdump.create_dump(exc_info=sys.exc_info(), threads=True, tasklets=True)
        self.assertIsInstance(p, type(b""))
        modules = sPickle.SPickleTools.getImportList(p)
        #pprint.pprint(modules)
        #sPickle.SPickleTools.dis(p)
        with open(self.dump_file_name, "wb") as f:
            f.write(p)

    def testLoadDump(self):
        dump = _pyheapdump.load_dump(self.dump_file_name)
        self.assertIsInstance(dump, dict)

    @unittest.skipUnless(RUN_INTERACTIVE_TESTS, "test requires manual interaction (breaks into the debugger)")
    def testDebugDump(self):
        _pyheapdump.debug_dump(self.dump_file_name)


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
