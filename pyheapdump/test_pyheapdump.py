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

import sys
import unittest
import sPickle
import tempfile
import os
import threading
import io
RUN_INTERACTIVE_TESTS = os.environ.get('RUN_INTERACTIVE_TESTS')

from pyheapdump import _pyheapdump


class BlockingPickle(object):
    def __init__(self, value=1):
        self.semaphore = threading.Semaphore(value)
        self.var = 0

    def __getstate__(self):
        self.semaphore.acquire()
        return dict(var=self.var)
        self.semaphore.release()


class PyheapdumpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super(PyheapdumpTest, cls).setUpClass()
        fd, name = tempfile.mkstemp(suffix=".pydump")
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
            p = _pyheapdump.create_dump(exc_info=sys.exc_info(), threads=None, tasklets=None)
        self.assertIsInstance(p, tuple)
        self.assertEqual(len(p), 2)
        self.assertIsInstance(p[0], bytes)
        self.assertIsInstance(p[1], dict)
        modules = sPickle.SPickleTools.getImportList(p[0])
        # pprint.pprint(modules)
        # sPickle.SPickleTools.dis(p)

    def testSaveDump(self):
        f = io.BytesIO()
        try:
            self.raise_exc()
        except Exception:
            _pyheapdump.save_dump(f, exc_info=sys.exc_info(), threads=None, tasklets=None)
        msg = f.getvalue()
        self.assertIsInstance(msg, bytes)
        self.assertIn(b'Content-Type: multipart/related; type="application/x.python-heapdump";', msg)
        self.assertIn(b'X-python-heapdump-version: 2', msg)
        # print(msg[:2000].decode("iso-8859-1"))

    def _writeDump(self):
        try:
            self.raise_exc()
        except Exception:
            _pyheapdump.save_dump(self.dump_file_name, exc_info=sys.exc_info(), threads=None, tasklets=None)

    def testLoadDump(self):
        self._writeDump()
        dump = _pyheapdump.load_dump(self.dump_file_name)
        self.assertIsInstance(dump, dict)
        self.assertEqual(dump['dump_version'], _pyheapdump.DUMP_VERSION)

    @unittest.skipUnless(RUN_INTERACTIVE_TESTS, "test requires manual interaction (breaks into the debugger)")
    def testDebugDump(self):
        apply(self._writeDump)
        print("Debugging dump file: ", self.dump_file_name)
        _pyheapdump.debug_dump(self.dump_file_name)


class UnpickleSurrogateTest(unittest.TestCase):
    def setUp(self):
        super(UnpickleSurrogateTest, self).setUp()
        self.surrogate = _pyheapdump.newUnpicklerSurrogate("test",
                                                           module=self.__class__.__module__,
                                                           name=self.__class__.__name__)

    def isSurrogateTest(self, surrogate):
        self.assertIsInstance(surrogate, _pyheapdump.AbstractSurrogate)
        self.assertIsNot(surrogate.__class__, _pyheapdump.AbstractSurrogate)

    def testNothing(self):
        self.isSurrogateTest(self.surrogate)

    def test__setitem__(self):
        self.surrogate["foo"] = "bar"
        self.assertIsInstance(self.surrogate, _pyheapdump.SurrogatePersonalityDict)
        self.assertDictEqual(self.surrogate._Surrogate__state._dict, dict(foo="bar"))

    def test_append(self):
        self.surrogate.append("foo")
        self.assertIsInstance(self.surrogate, _pyheapdump.SurrogatePersonalityList)
        self.assertListEqual(self.surrogate._Surrogate__state._list, ["foo"])

    def test_extend(self):
        l = ["foo", "bar"]
        self.surrogate.extend(l)
        self.assertIsInstance(self.surrogate, _pyheapdump.SurrogatePersonalityList)
        self.assertListEqual(self.surrogate._Surrogate__state._list, l)

    def test_instantiate(self):
        surrogate2 = _pyheapdump.newUnpicklerSurrogate("_instantiate", func=self.surrogate, args=())
        self.isSurrogateTest(surrogate2)
        self.assertIsInstance(surrogate2, self.surrogate._Surrogate__state._class)

    def test__new__(self):
        surrogate2 = self.surrogate.__new__(self.surrogate)
        self.isSurrogateTest(surrogate2)
        self.assertIsInstance(surrogate2, self.surrogate._Surrogate__state._class)


if __name__ == "__main__":
    unittest.main()
