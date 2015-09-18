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

DUMP_VERSION = 2
# for now we export just a limited set of symbols.
__all__ = ('save_dump', 'create_dump', 'load_dump',
           'debug_dump', 'MimeMessageFormatter', 'dump_on_unhandled_exceptions')

import os
import sys
import types
import thread
import threading
import collections
import pickle
import linecache
import inspect
import contextlib
import traceback
import weakref
import datetime
import warnings
import re
import logging
import tempfile
import functools
import io
from email import header, message_from_file, message_from_string, message
from email.mime import application, multipart
from email.utils import formatdate

import sPickle

LOGGER_NAME = __name__

try:
    from threading import main_thread
except ImportError:
    try:
        from stackless import getmain
    except ImportError:
        def _build():
            _main_thread_id = thread.get_ident()

            def main_thread_id():
                return _main_thread_id
            return main_thread_id
    else:
        def _build():
            _getmain = getmain

            def main_thread_id():
                return _getmain().thread_id
            return main_thread_id
else:
    def _build():
        _main_thread = main_thread

        def main_thread_id():
            return _main_thread().ident
        return main_thread_id
main_thread_id = _build()
del _build


class _Lock_Status_Base(object):
    iolock = threading.RLock()

    def __init__(self):
        self.is_locked = True
        self.has_io_lock = False

    def __call__(self):
        return self

    def unlock(self):
        if self.is_locked:
            self.is_locked = False
            self._unlock()
        if self.has_io_lock:
            self.has_io_lock = False
            self.iolock.release()

    @contextlib.contextmanager
    def context_with_io(self):
        has_io_lock = self.iolock.acquire(blocking=False)
        self.has_io_lock = has_io_lock
        self._unlock()
        if not has_io_lock:
            self.iolock.acquire(blocking=True)
            self.has_io_lock = True
        self.is_locked = False
        yield

# A variant with the gil_hacks context manager.
# Unfortunately, this requires a modified python
#     @contextlib.contextmanager
#     def context_with_io(self):
#         if use_gil_atomic:
#             mgr = gil_hacks_atomic
#         else:
#             mgr = null_gil_hacks_atomic
#         mgr = mgr(sys.getcheckinterval())
#         __exit__ = mgr.__exit__
#         mgr.__enter__()
#         try:
#             yield
#         except:
#             __exit__(*sys.exc_info())
#             raise
#         else:
#             __exit__(None, None, None)

try:
    import stackless
except ImportError:
    isStackless = False

    class taskletType(object):
        def __new__(cls, *args, **kw):
            raise RuntimeError("Can't instantiate fake class")

    def run_in_tasklet(func, *args, **kw):
        return func(*args, **kw)

    @contextlib.contextmanager
    def atomic():
        yield

    @contextlib.contextmanager
    def block_trap():
        yield

    class _Lock_Status(_Lock_Status_Base):
        def __init__(self, checkinterval):
            super(_Lock_Status, self).__init__()
            self.checkinterval = checkinterval

        def _unlock(self):
            sys.setcheckinterval(self.checkinterval)

    def lock_function(getcheckinterval=sys.getcheckinterval, setcheckinterval=sys.setcheckinterval, maxint=sys.maxint):
        # create an atomic context
        old_value = getcheckinterval()
        setcheckinterval(maxint)
        return _Lock_Status(old_value)

else:
    isStackless = True

    taskletType = stackless.tasklet
    atomic = stackless.atomic

    class _Stackless_Lock_Status(_Lock_Status_Base):
        def __init__(self, is_atomic):
            super(_Stackless_Lock_Status, self).__init__()
            self.is_atomic = is_atomic

        def _unlock(self):
            stackless.current.set_atomic(self.is_atomic)  # @UndefinedVariable

    def lock_function():
        # create an atomic context
        old_value = stackless.current.set_atomic(1)  # @UndefinedVariable
        return _Stackless_Lock_Status(old_value)

    def _run_in_tasklet_call_func(result, current_tasklet, func, args, kw):
        try:
            result.append(func(*args, current_tasklet=current_tasklet, **kw))
        except Exception:
            exc_info = sys.exc_info()
            current_tasklet.throw(exc=exc_info[0], val=exc_info[1], tb=exc_info[2])
        else:
            current_tasklet.switch()

    def run_in_tasklet(func, *args, **kw):
        current = stackless.current  # @UndefinedVariable
        result = []

        result.append(stackless.tasklet())
        result[0].set_atomic(True)
        result.pop().bind(_run_in_tasklet_call_func, (result, current, func, args, kw)).switch()
        return result[0]

    @contextlib.contextmanager
    def block_trap():
        stackless.current.block_trap = True
        try:
            yield
        finally:
            stackless.current.block_trap = False


@contextlib.contextmanager
def high_recusion_limit(factor=4):
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(old * factor)
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


# API
class HeapDumper(object):
    sequence_number = -1

    @classmethod
    def next_sequence_number(cls):
        cls.sequence_number += 1
        return cls.sequence_number

    def save_dump(self, filename, tb=None, exc_info=None, threads=None,
                  tasklets=None, headers=None, files=None, formatter=None,
                  lock_function=lock_function):
        """
        Create and save a Python heap-dump.

        This function will usually be called from an except block to
        allow post-mortem debugging of a failed process. The function calls
        the function :func:`create_dump` to create the dump.

        The saved file can be loaded with :func:`load_dump` or :func:`debug_dump`, which recreates
        traceback / thread and tasklet objects and passes them to a Python debugger.

        The simplest way to do that is to run::

           $ python -m pyheapdump my_dump_file.dump

        Arguments

        :param filename: name of the dump-file
        :type filename: str
        :param tb: an optional traceback. This parameter exists for compatibility with the Python module :mod:`pydump`.
        :type tb: types.TracebackType
        :param exc_info: optional exception info tuple as returned by :func:`sys.exc_info`. If set to `None`, the value
            returned by :func:`sys.exc_info` will be used. If set to `True`, :func:`save_dump` does not add
            exception information to the dump.
        :param threads: A single thread id (type is `int`) or a sequence of thread ids (type is :class:`collections.Sequence`)
            or `None` for all threads (default) or `False` to omit thread information altogether.
        :param tasklets: Stackless Python only: either `None` for all tasklets (default) or `False` to omit tasklet information altogether.
        :param headers: a mutable mapping, that contains header lines. All keys must be unicode strings. Values must be text, bytes or None.
        :type headers: collections.MutableMapping
        :param files: this argument controls, if the heap dump contains the source code of those Python files, that contribute
            to the dumped frames. If *files* is a container, a file is included, if its name is in the container. Otherwise, if *files* is a
            callable, it will be called with a file name as its single argument. If the callable returns a true-value, the file
            will be included. Otherwise, if *files* is a true-value, all files are included. Lastly, if *files* is `None`, a default
            behaviour applies which is currently to include all files.
        :param formatter: the formatter to be used. The formatter must be a callable with two arguments *pickle* and *headers* that returns the
                          bytes of the heap dump file. See :class:`MimeMessageFormatter` for an example.
        :param lock_function: Used internally. Do not set this argument!
        :returns: A tuple of length 2: the name of the dump file and the headers dictionary.
        """
        lock_function = lock_function()
        try:
            if tb is not None and exc_info is None:
                exc_info = (None, None, tb)
            pickle, headers = self.create_dump(exc_info=exc_info, threads=threads, tasklets=tasklets,
                                               headers=headers, files=files,
                                               lock_function=lock_function)
            try:
                sequence_number = headers['sequence_number']
            except Exception:
                sequence_number = '0'
            if isinstance(filename, basestring) and '{sequence_number}' in filename:
                filename = filename.replace('{sequence_number}', sequence_number)

            if formatter is None:
                formatter = DEFAULT_FORMATTER
            try:
                write = filename.write
            except AttributeError:
                with open(filename, 'wb') as f:
                    f.write(formatter(pickle, headers))
            else:
                write(formatter(pickle, headers))
            return filename, headers
        finally:
            lock_function.unlock()

    def create_dump(self, exc_info=None, threads=None, tasklets=None, headers=None, files=None,
                    lock_function=lock_function):
        """
        Create a Python heap-dump.

        This function creates a Python dump. The dump contains various
        informations about the currently executing Python program:

         * exception information
         * threads
         * tasklets

        The exact content depends on the function arguments.

        This function tries to prevent thread context switches during the creation of the
        dump. On Stackless it uses the tasklet flag :attr:`~stackless.tasklet.atomic`. Otherwise
        it temporarily manipulates the check-interval. Additionally this function
        temporarily increases the recursion limit.

        This function will usually be called from an except block to
        allow post-mortem debugging of a failed process. The function returns
        a byte string, that can be loaded with :func:`load_dump` or :func:`debug_dump`.

        Arguments

        :param filename: name of the dump-file
        :type filename: str
        :param exc_info: optional exception info tuple as returned by :func:`sys.exc_info`. If set to `None`, the value
            returned by :func:`sys.exc_info` will be used. If set to `False`, :func:`save_dump` does not add
            exception information to the dump.
        :param threads: A single thread id (type is `int`) or a sequence of thread ids (type is :class:`collections.Sequence`)
            or `None` for all threads (default) or `False` to omit thread information altogether.
        :param tasklets: Stackless Python only: either `None` for all tasklets (default) or `False` to omit tasklet information altogether.
        :param headers: a mutable mapping, that contains header lines. All keys must be unicode strings. Values must be text, bytes or None.
        :type headers: collections.MutableMapping
        :param files: this argument controls, if the heap dump contains the source code of those Python files, that contribute
            to the dumped frames. If *files* is a container, a file is included, if its name is in the container. Otherwise, if *files* is a
            callable, it will be called with a file name as its single argument. If the callable returns a true-value, the file
            will be included. Otherwise, if *files* is a true-value, all files are included. Lastly, if *files* is `None`, a default
            behaviour applies which is currently to include all files.
        :param lock_function: Used internally. Do not set this argument!
        :returns: the compressed pickle of the heap-dump, the updated headers collection
        :rtype: tuple
        """
        lock_function = lock_function()
        try:
            with high_recusion_limit():
                return run_in_tasklet(self._create_dump_impl, exc_info=exc_info, threads=threads,
                                      tasklets=tasklets, headers=headers, files=files,
                                      lock_function=lock_function)
        finally:
            lock_function.unlock()

    def _create_dump_impl(self, exc_info=None, threads=None, tasklets=None, current_tasklet=None,
                          headers=None, files=None, lock_function=lock_function):
        """
        Implementation of :func:`create_dump`.
        """
        lock_function = lock_function()
        if isinstance(files, collections.Container):
            def files_filter(name, container=files):
                return name in container
        elif callable(files):
            files_filter = files
        else:
            if files is None:
                files = True

            def files_filter(name, const=bool(files)):
                return const

        try:
            with atomic(), high_recusion_limit():
                sequence_number = self.next_sequence_number()
                pid = os.getpid()
                files = {}
                memo = {}
                dump = {'dump_version': DUMP_VERSION,
                        'files': files,
                        'sequence_number': sequence_number,
                        'pid': pid,
                        'pathmodule': os.path.__name__}
                # add exception information
                if exc_info is not False:
                    if exc_info is None:
                        exc_info = sys.exc_info()
                    dump['exception_class'] = exc_info[0]
                    dump['exception'] = exc_info[1]
                    dump['traceback'] = FakeTraceback.for_tb(exc_info[2], memo)

                # add threads
                current_thread_id = thread.get_ident()
                dump['current_thread_id'] = current_thread_id
                dump['main_thread_id'] = main_thread_id()

                current_frames = sys._current_frames()
                if threads is None:
                    threads = current_frames.keys()
                elif isinstance(threads, int):
                    threads = [threads]
                elif isinstance(threads, (list, tuple, collections.Sequence)):
                    threads = list(threads)

                # add tasklets
                if isStackless and tasklets is not False:
                    dump['tasklets'] = self._collect_tasklets(current_tasklet, threads, memo)
                    if dump['tasklets']:
                        threads = False

                if threads:
                    thread_frames = {}
                    dump['thread_frames'] = thread_frames
                    for tid in threads:
                        try:
                            frame = current_frames[tid]
                        except KeyError:
                            pass
                        else:
                            thread_frames[tid] = FakeFrame.for_frame(frame, memo)
                            # del frame
                    del thread_frames
                del memo
                # unlock threads. No operation, that might release the GIL before this point !!!
                with lock_function.context_with_io():

                    # get files for frames
                    if 'traceback' in dump:
                        _get_traceback_files(dump['traceback'], files=files, files_filter=files_filter)
                    d = dump.get('thread_frames', ())
                    for tid in d:
                        _get_frame_files(d[tid], files=files, files_filter=files_filter)
                    d = dump.get('tasklets', ())
                    for tid in d:
                        main, current, other = d[tid]
                        _get_tasklet_files(main, files=files, files_filter=files_filter)
                        _get_tasklet_files(current, files=files, files_filter=files_filter)
                        for t in other.values():
                            _get_tasklet_files(t, files=files, files_filter=files_filter)

                    d = main = current = other = t = None

                    del current_frames
                    del exc_info
                    del files
                    del files_filter

                    try:
                        # pickle
                        pt = sPickle.SPickleTools(pickler_class=DumpPickler)
                        with block_trap():
                            pickle = pt.dumps(dump)
                        pt = None

                        if headers is None:
                            headers = {}
                        headers = self.fill_headers(headers, dump, pickle)
                        return pickle, headers
                    finally:
                        dump.clear()
        finally:
            lock_function.unlock()

    def _collect_tasklets(self, current_tasklet, threads, memo):
        taskletType = stackless.tasklet
        this_tasklet = stackless.current  # @UndefinedVariable
        tasklets = {}
        for tid in threads:
            main, current = stackless.get_thread_info(tid)[:2]

            #
            # find scheduled tasklets
            #
            t = current.next
            if current is this_tasklet:
                current = current_tasklet

            assert current is not this_tasklet
            assert main is not this_tasklet

            current = FakeTasklet.for_tasklet(current, memo)
            main = FakeTasklet.for_tasklet(main, memo)

            other = {id(current): current}
            other[id(main)] = main
            while t is not None and t is not this_tasklet:
                fake = FakeTasklet.for_tasklet(t, memo)
                oid = id(fake)
                if oid in other:
                    break
                other[oid] = fake
                t = t.next

            #
            # Here we could look at other tasklet-holders too
            #

            tasklets[tid] = (main, current, other)
        return tasklets

    def compute_description(self, dump, pickle):
        """
        Compute the informational description for the dump.

        This implementation returns None. A sub-class my overwrite
        this method.

        :param dump: the content of the dump
        :type dump: dict
        :param pickle: the (compressed) pickle of *dump*
        :type pickle: bytes
        :returns: the human readable description
        :rtype: unicode string or None
        """
        return None

    def fill_headers(self, headers, dump, pickle):
        """
        This method fills in meta information about the dump.

        A subclass may override this method.

        :param headers: a dictionary
        :type headers: dict
        :param description: the human readable description
        :type description: unicode or None
        :param dump: the content of the dump
        :type dump: dict
        :param pickle: the (compressed) pickle of *dump*
        :type pickle: bytes
        :returns: a pickleable mapping object with meta information, usually headers
        :rtype: usually dict
        """
        if not isinstance(headers, collections.MutableMapping):
            # A custom meta data type is used.
            return headers

        if 'version' not in headers:
            headers['version'] = str(DUMP_VERSION)
        if 'utcnow' not in headers:
            headers['utcnow'] = datetime.datetime.utcnow().isoformat()
        if 'pid' not in headers:
            headers['pid'] = str(dump['pid'])
        if 'sequence_number' not in headers:
            headers['sequence_number'] = str(dump['sequence_number'])
        if 'sys_version_info' not in headers:
            headers['sys_version_info'] = repr(sys.version_info)
        if 'sys_flags' not in headers:
            headers['sys_flags'] = repr(sys.flags)
        if 'sys_executable' not in headers:
            headers['sys_executable'] = sys.executable
        if 'sys_argv' not in headers:
            headers['sys_argv'] = repr(sys.argv)
        if 'sys_path' not in headers:
            headers['sys_path'] = repr(sys.path)
        return headers


class BinaryFormatter(object):
    def __call__(self, pickle, headers):
        return pickle


class MimeMessageFormatter(object):
    """
    This class formats a heap-dump as a MIME-message.

    Methods:

    .. automethod:: __call__
    """
    _ASCII_HEADER_RE = re.compile("[^ \x21-\x7e]")
    CONTENT_TYPE_HEAPDUMP = b"x.python-heapdump"
    HEADER_SUBJECT = u"Subject"
    HEADER_DATE = u"Date"
    HEADER_MSGID = u"Message-ID"

    HEADER_NAME_MAPPING = {
        u"description": HEADER_SUBJECT,
        u"date": HEADER_DATE,
        u"id": HEADER_MSGID
    }

    HEADER_PREFIX = u'X-python-heapdump-'

    PREAMBLE = b"""This file is a dump of the internal state of a Python program.
This information helps analysing program failures.
(Although this file uses the MIME-format, it is not an e-mail message.)

Run
   python -m pyheapdump [OPTIONS] <path_and_name_of_this_file>
to inspect this file using eclipse Pydev or pdb. To get help, run
   python -m pyheapdump --help

"""

    def __init__(self, ensure_ascii=True, unixfrom=False, preamble=None):
        self.ensure_ascii = ensure_ascii
        self.unixfrom = unixfrom
        if preamble is not None:
            self.PREAMBLE = preamble

    def __call__(self, pickle, headers):
        """
        Format the *pickle* and the *headres* as a flat byte string.

        :param pickle: the compressed pickle of the heap dump
        :type pickle: bytes
        :param headers: a mapping
        :type headers: collections.Mapping
        :returns: a MIME message
        :rtype: bytes
        """
        msg = multipart.MIMEMultipart("related", type="application/" + self.CONTENT_TYPE_HEAPDUMP)
        msg2 = application.MIMEApplication(pickle, self.CONTENT_TYPE_HEAPDUMP)
        msg.attach(msg2)
        msg.preamble = self.PREAMBLE
        for k in sorted(headers):
            v = headers[k]
            if not v:
                continue
            if not isinstance(v, basestring):
                warnings.warn("pyheapdump: ignoring non string header")
                continue

            k = self.HEADER_NAME_MAPPING.get(k, self.HEADER_PREFIX + k)
            target = msg2 if k.startswith(self.HEADER_PREFIX) else msg

            if self._ASCII_HEADER_RE.search(v) is None and v.strip() == v:
                target[k] = header.Header(v, maxlinelen=2000000000, header_name=k)
            elif isinstance(v, bytes):
                target[k] = header.Header(v, charset="iso-8859-1", header_name=k)
            else:
                target[k] = header.Header(v.encode("utf-8"), charset="utf-8", header_name=k)
        if self.HEADER_DATE not in msg:
            msg[self.HEADER_DATE] = formatdate(localtime=True)
        return msg.as_string(self.unixfrom)


DEFAULT_HEAP_DUMPER = HeapDumper()
"""Default instance of class :class:`HeapDumper`

Used by the functions :func:`save_dump` and :func:`create_dump`"""

DEFAULT_FORMATTER = MimeMessageFormatter()
"""Default formatter."""


def save_dump(filename, tb=None, exc_info=None, threads=None, tasklets=None, headers=None,
              files=None, formatter=None, lock_function=lock_function):
    lock_function = lock_function()
    return DEFAULT_HEAP_DUMPER.save_dump(filename, tb, exc_info, threads, tasklets,
                                         headers, files, formatter, lock_function=lock_function)
save_dump.__doc__ = DEFAULT_HEAP_DUMPER.save_dump.__doc__


def create_dump(exc_info=None, threads=None, tasklets=None, headers=None, files=None, lock_function=lock_function):
    lock_function = lock_function()
    return DEFAULT_HEAP_DUMPER.create_dump(exc_info, threads, tasklets, headers, files, lock_function=lock_function)
create_dump.__doc__ = DEFAULT_HEAP_DUMPER.create_dump.__doc__


class DumpPickler(sPickle.FailSavePickler):

    def __init__(self, *args, **kw):
        logger = logging.getLogger(LOGGER_NAME).getChild("pickler")
        logger.setLevel(logging.CRITICAL)
        self.__class__.__bases__[0].__init__(self, *args, logger=logger, **kw)
        self.dispatch[types.TracebackType] = self.saveTraceback.__func__
        self.dispatch[weakref.ReferenceType] = self.saveWeakref.__func__
        self.__tracebacks = {}

    def dump(self, obj):
        assert isinstance(obj, dict)
        self.__dump = obj
        obj.setdefault('weakly_referenced_objects', [])

        sPickle.FailSavePickler.dump(self, obj)

    def saveWeakref(self, obj):
        r = obj()
        if r is not None:
            self.save_reduce(_dumppickler_create_weakref, (r, self.__dump['weakly_referenced_objects']), obj=obj)
        else:
            # use an new object.
            self.save_reduce(weakref.ref, (collections.OrderedDict(),), obj=obj)

    def saveTraceback(self, obj):
        """
        Save a traceback as a FakeTraceback object

        Note, that the FakeTraceback also uses FakeFrames. This way a traceback
        never causes the pickler to see a real frame.
        """
        fake_tb = FakeTraceback.for_tb(obj, self.__tracebacks)
        return self.save(self._ObjReplacementContainer(obj, fake_tb))

    def get_replacement(self, pickler, obj, exception):
        """
        Replace unpickleable objects
        """
        if isinstance(obj, types.FrameType):
            return FakeFrame.for_frame(obj, self.__tracebacks)
        elif isinstance(obj, taskletType):
            if obj.is_current:
                return TaskletReplacement(obj)
            else:
                return FakeClass("Fake Tasklet", dict(thread_id=obj.thread_id, is_current=obj.is_current,
                                                      is_main=obj.is_main, alive=obj.alive, paused=obj.paused,
                                                      blocked=obj.blocked, scheduled=obj.scheduled))

        # the hard case: an unknown and perhaps misbehaving object
        try:
            members = inspect.getmembers(obj)
        except SystemExit:
            raise
        except:
            sys.exc_clear()
            members = []
        d = {}
        for k, v in members:
            try:
                if not isinstance(k, basestring):
                    continue
                if k.startswith('__') and k.endswith('__'):
                    k = type(k)('_') + k
                d[k] = v
            except SystemExit:
                raise
            except:
                sys.exc_clear()
        return FakeClass(_safe_repr(obj), d)


def _dumppickler_create_weakref(obj, memo):
    memo.append(obj)
    return weakref.ref(obj)


class TaskletReplacement(object):
    def __init__(self, tasklet):
        self.tasklet = tasklet

    def __reduce__(self):
        tasklet = self.tasklet
        if tasklet is stackless.current:  # @UndefinedVariable
            raise pickle.PickleError("Can't pickle the current tasklet")
        try:
            return tasklet.__reduce__()
        except RuntimeError:
            if not tasklet.is_current:
                raise
        fl = []
        f = tasklet.frame
        tempvap = tasklet.tempval
        nesting_level = tasklet.nesting_level
        flags = ((tasklet.blocked & 3) +
                 ((tasklet.atomic & 1) << 2) +
                 ((tasklet.ignore_nesting & 1) << 3) +
                 ((tasklet.block_trap & 1) << 5))
        while f is not None:
            fl.append(f)
            f = f.f_back
        fl.reverse()
        return (tasklet.__class__, (), (flags, tempvap, nesting_level, fl))


class FakeClass(object):
    def __init__(self, repr_, vars_):
        self.__repr = repr_
        self.__dict__.update(vars_)

    def __repr__(self):
        return self.__repr


class FakeTasklet(object):
    __slots__ = ('alive', 'paused', 'blocked', 'scheduled', 'restorable',
                 'atomic', 'ignore_nesting', 'block_trap',
                 'is_current', 'is_main', 'thread_id',
                 'prev', 'next',
                 'tempval', 'nesting_level', 'frame')

    @classmethod
    def for_tasklet(cls, tasklet, memo):
        if tasklet is None or isinstance(tasklet, FakeTasklet):
            return tasklet
        oid = id(tasklet)
        try:
            return memo[oid]
        except KeyError:
            fake_tasklet = cls()
            memo[oid] = fake_tasklet
            fake_tasklet.alive = tasklet.alive
            fake_tasklet.paused = tasklet.paused
            fake_tasklet.blocked = tasklet.blocked
            fake_tasklet.scheduled = tasklet.scheduled
            fake_tasklet.restorable = tasklet.restorable
            fake_tasklet.atomic = tasklet.atomic
            fake_tasklet.ignore_nesting = tasklet.ignore_nesting
            fake_tasklet.block_trap = tasklet.block_trap
            fake_tasklet.is_current = tasklet.is_current
            fake_tasklet.is_main = tasklet.is_main
            fake_tasklet.thread_id = tasklet.thread_id
            fake_tasklet.prev = cls.for_tasklet(tasklet.prev, memo)
            fake_tasklet.next = cls.for_tasklet(tasklet.next, memo)
            fake_tasklet.nesting_level = tasklet.nesting_level
            fake_tasklet.frame = FakeFrame.for_frame(tasklet.frame, memo)
            tmp = tasklet.tempval
            if isinstance(tmp, stackless.tasklet):
                tmp = cls.for_tasklet(tmp, memo)
            elif isinstance(tmp, types.FrameType):
                tmp = FakeFrame.for_frame(tmp, memo)
            elif isinstance(tmp, types.TracebackType):
                tmp = FakeTraceback.for_tb(tmp, memo)
            fake_tasklet.tempval = tmp
            return fake_tasklet


class FakeFrame(object):
    __slots__ = ('f_back', 'f_builtins', 'f_code', 'f_exc_traceback', 'f_exc_type', 'f_exc_value',
                 'f_globals', 'f_lasti', 'f_lineno', 'f_locals', 'f_restricted', 'f_trace')

    @classmethod
    def for_frame(cls, frame, memo):
        if frame is None or isinstance(frame, FakeFrame):
            return frame
        oid = id(frame)
        try:
            return memo[oid]
        except KeyError:
            fake_frame = cls()
            memo[oid] = fake_frame
            fake_frame.f_back = cls.for_frame(frame.f_back, memo)
            fake_frame.f_builtins = frame.f_builtins
            fake_frame.f_code = frame.f_code
            fake_frame.f_exc_traceback = frame.f_exc_traceback
            fake_frame.f_exc_type = frame.f_exc_type
            fake_frame.f_exc_value = frame.f_exc_value
            fake_frame.f_globals = frame.f_globals
            fake_frame.f_lasti = frame.f_lasti
            fake_frame.f_lineno = frame.f_lineno
            fake_frame.f_locals = frame.f_locals
            # work around http://bugs.python.org/issue21967
            # fake_frame.f_restricted = frame.f_restricted
            fake_frame.f_restricted = False
            fake_frame.f_trace = frame.f_trace
            return fake_frame


class FakeTraceback(object):
    __slots__ = ('tb_frame', 'tb_lasti', 'tb_lineno', 'tb_next')

    @classmethod
    def for_tb(cls, traceback, memo):
        if traceback is None or isinstance(traceback, FakeTraceback):
            return traceback
        oid = id(traceback)
        try:
            return memo[oid]
        except KeyError:
            fake_tb = cls()
            memo[oid] = fake_tb
            fake_tb.tb_frame = FakeFrame.for_frame(traceback.tb_frame, memo)
            fake_tb.tb_lasti = traceback.tb_lasti
            fake_tb.tb_lineno = traceback.tb_lineno
            fake_tb.tb_next = cls.for_tb(traceback.tb_next, memo)
            return fake_tb


def _get_tasklet_files(tasklet, files=None, files_filter=None):
    try:
        frame = tasklet.frame
    except AttributeError:
        if files is None:
            files = {}
        return files  # not a tasklet
    else:
        return _get_frame_files(frame, files, files_filter)


def _get_traceback_files(traceback, files=None, files_filter=None):
    if files is None:
        files = {}
    while traceback:
        _get_frame_files(traceback.tb_frame, files, files_filter)
        traceback = traceback.tb_next
    return files

FILE_NOT_FOUND_PREFIX = "couldn't locate"


def _accept_always(name):
    return True


def _get_frame_files(frame, files, files_filter=None):
    if files_filter is None:
        files_filter = _accept_always
    while frame:
        filename0 = inspect.getsourcefile(frame.f_code)
        if filename0 is not None:
            filename1 = os.path.normcase(os.path.normpath(filename0))
            filename2 = os.path.normcase(os.path.abspath(filename1))
            if files_filter(filename0) or files_filter(filename1) or files_filter(filename2):
                if filename0 not in files:
                    try:
                        files[filename0] = open(filename0, 'rb').read()
                    except IOError:
                        files[filename0] = FILE_NOT_FOUND_PREFIX + " '%s' during dump" % filename0
                if filename1 not in files:
                    files[filename1] = files[filename0]
                if filename2 not in files:
                    files[filename2] = files[filename0]
        frame = frame.f_back
    return files


def _safe_repr(v):
    try:
        return repr(v)
    except Exception, e:
        return "repr error: " + str(e)


def load_dump(dumpfile=None, dump=None):
    """
    Load a Python heap dump

    This function loads and preprocesses a Python dump file or
    a Python dump string or an already unpickled heap dump dictionary.

    Arguments

    :param dumpfile: the name of the heap-dump file or a file-like object open for reading bytes.
    :type dumpfile: string or file-like
    :param dump: The content of a heap-dump file (bytes) or
       a compressed pickle (bytes, starts with ``b"BZh9"``) or
       a MIME-message with content type ``application/x.python-heapdump``
       or the already unpickled heap dump dictionary. Exactly one of the two arguments *dumpfile*
       and *dump* must be given.
    :type dump: bytes or :class:`~email.message.Message` or dict
    :returns: the preprocessed heap dump dictionary
    :rtype: dict
    """
    if dump is None:
        if isinstance(dumpfile, basestring):
            with open(dumpfile, 'rb') as f:
                dump = message_from_file(f)
        else:
            dump = message_from_file(dumpfile)
    elif isinstance(dump, bytes) and not dump.startswith(b"BZh9"):
        # not a compressed pickle. Perhaps a message
        dump = message_from_string(dump)
    if isinstance(dump, message.Message):
        def handle_payload(msg):
            if msg.is_multipart():
                for m in msg.get_payload():
                    r = handle_payload(m)
                    if r is not None:
                        return r
                return None
            if msg.get_content_maintype() == "application":
                subtype = msg.get_content_subtype()
                if subtype == MimeMessageFormatter.CONTENT_TYPE_HEAPDUMP:
                    return msg.get_payload(decode=True)
            return None
        r = handle_payload(dump)
        if r is None:
            raise RuntimeError("Not a pyheapdump IMF message")
        dump = r
    if isinstance(dump, bytes):
        dump = sPickle.SPickleTools.loads(dump, unpickler_class=FailSaveUnpickler)
    if 'tasklets' in dump and 'thread_frames' not in dump:
        # Stackless
        tf = {}
        dump['thread_frames'] = tf
        for tid, value in dump['tasklets'].iteritems():
            frame = value[1].frame
            if frame is not None:
                tf[tid] = frame
    tb = dump.get('traceback')
    if isinstance(tb, types.TracebackType) and tb.tb_next is not None:
        # Stackless and a traceback with more than one levels
        #
        # Fix the links of the frames.
        # If stackless pickles a frame, the f_back attribute will be None after unpickling.
        # That's a shortcoming, I can't fix.

        # find the last tb with a valid frame
        tbs = [tb]
        first_frame = tb.tb_frame
        assert first_frame is not None
        tb = tb.tb_next
        while tb is not None:
            assert tb.tb_frame is not None
            if tb.tb_frame.f_back is None:
                break
            tbs.append(tb)
            first_frame = tb.tb_frame
            tb = tb.tb_next
        # now tb is either none or the first traceback with unchained frames
        fl = [first_frame]
        while tb is not None:
            assert tb.tb_frame is not None
            assert tb.tb_frame.f_back is None
            tbs.append(tb)
            fl.append(tb.tb_frame)
            tb = tb.tb_next

        # and now the black magic: we can't set the f_back attributes,
        # but tasklet.__setstate__ can
        t = taskletType().__setstate__((0, None, 0, fl))
        dump['traceback_tasklet'] = t  # keep the tasklet alive
        # now reconstruct the traceback objects starting at the first
        # object, that had a not None f_back

        # first skip the frames, where f_back was None
        frame = t.frame
        tb_next = None
        while tbs and frame is tbs[-1].tb_frame:
            tb_next = tbs.pop()
            frame = frame.f_back
        # now reconstruct the Traceback objects
        tbWrapType = stackless._wrap.traceback
        while tbs:
            assert frame is not None
            tb = tbs.pop()
            state = (frame, tb.tb_lasti, tb.tb_lineno)
            if tb_next is not None:
                state += (tb_next,)

            new_tb = tbWrapType()
            new_tb.__setstate__(state)  # mutates the type of new_tb
            tb_next = new_tb
        dump['traceback'] = tb_next

    return dump


def invoke_pdb(dump, debugger_options):
    import pdb
    _cache_files(dump['files'])
    _old_checkcache = linecache.checkcache
    linecache.checkcache = lambda filename=None: None  # @IgnorePep8
    try:
        pdb.post_mortem(dump['traceback'])
    finally:
        linecache.checkcache = _old_checkcache


def invoke_pydevd(dump, debugger_options):
    import pydevd  # @UnresolvedImport
    from pydevd_custom_frames import addCustomFrame  # @UnresolvedImport

    class IoBuffer(object):
        __slots__ = ('msg',)

        def __init__(self, msg):
            self.msg = msg

        def getvalue(self):
            return self.msg

    def debugerWrite(msg, stderr=False):
        debugger = pydevd.GetGlobalDebugger()
        if debugger is None:
            return
        debugger.checkOutput(IoBuffer(msg), 2 if stderr else 1)

    def debugerWriteMsg(lines):
        eol = '\n'
        if isinstance(lines, basestring):
            lines = lines.split('\n')
        for l in lines:
            if not l.endswith(eol):
                l += eol
            debugerWrite(l, stderr=True)

    files = dump.get('files')
    if files:
        # we monkey patch the global namespace of PyDB.processNetCommand

        class MonkeyPatchAttr(object):
            def __init__(self, baseobj, name, replacement):
                self.__baseobj = baseobj
                self.__name = name
                self.__replacement = replacement

            def __getattr__(self, name):
                if name == self.__name:
                    return self.__replacement
                return getattr(self.__baseobj, name)

        pathmodule = dump.get('pathmodule', os.path.__name__)
        __import__(pathmodule)
        pathmodule = sys.modules[pathmodule]

        def get_file(name):
            try:
                f = files[name]
            except KeyError:
                name = pathmodule.normcase(pathmodule.normpath(name))
                try:
                    f = files[name]
                except KeyError:
                    # print("\n         get_file: KeyError", file=sys.stderr)
                    return None
            if f.startswith(FILE_NOT_FOUND_PREFIX):
                # print("\n         get_file: PREFIX", file=sys.stderr)
                return None
            # print("\n         get_file: ", repr(name), file=sys.stderr)
            return f

        def mp_exists(path):
            # print("\n------ mp_exists: ", repr(path), file=sys.stderr)
            if get_file(path) is not None:
                return True
            return os.path.exists(path)

        def mp_open(name, *args, **kw):
            # print("\n------ mp_open: ", repr(name), file=sys.stderr)
            f = get_file(name)
            if f is not None:
                return io.BytesIO(f)
            return open(name, *args, **kw)

        PyDB = pydevd.PyDB
        pnc = PyDB.processNetCommand
        if not isinstance(pnc, types.FunctionType):
            pnc = pnc.__func__

        # create the new globals dictionary
        mp_globals = dict(pnc.__globals__)
        mp_globals['os'] = MonkeyPatchAttr(os, 'path', MonkeyPatchAttr(os.path, 'exists', mp_exists))
        mp_globals['open'] = mp_open

        # recreate the method using the new globals dictionary
        mp_processNetCommand = types.FunctionType(pnc.__code__, mp_globals, pnc.__name__, pnc.__defaults__, pnc.__closure__)
        for name in ('__doc__', '__dict__', '__module__', '__qualname__', '__annotations__', '__kwdefaults__'):
            try:
                setattr(mp_processNetCommand, name, getattr(pnc, name))
            except AttributeError:
                pass
        PyDB.processNetCommand = mp_processNetCommand

    current_thread_id = thread.get_ident()
    current_thread = threading.current_thread()
    pydevd.settrace(host=debugger_options.get('host'),
                    port=debugger_options.get('port', 5678),
                    stdoutToServer=debugger_options.get('stdout') == 'server',
                    stderrToServer=debugger_options.get('stderr') == 'server',
                    suspend=False, trace_only_current_thread=True)

    ctid = dump.get('current_thread_id', 0)
    mtid = dump.get('main_thread_id', 0)

    if dump.get('tasklets'):
        for tid, value in dump['tasklets'].iteritems():
            tasklet = value[0]
            if tasklet.frame is not None:
                addCustomFrame(tasklet.frame, _tasklet_name(tasklet, tid, is_main=True, is_current=(tasklet is value[1]),
                                                            main_thread_id=mtid, current_thread_id=ctid), current_thread_id)
            tasklet = value[1]
            if tasklet.frame is not None and tasklet is not value[0]:
                addCustomFrame(tasklet.frame, _tasklet_name(tasklet, tid, is_current=True,
                                                            main_thread_id=mtid, current_thread_id=ctid), current_thread_id)
            for oid in value[2]:
                tasklet = value[2][oid]
                if tasklet is value[0] or tasklet is value[1] or tasklet.frame is None:
                    continue
                addCustomFrame(tasklet.frame, _tasklet_name(tasklet, tid,
                                                            main_thread_id=mtid, current_thread_id=ctid), current_thread_id)
    elif 'thread_frames' in dump:
        for tid, frame in dump['thread_frames'].iteritems():
            addCustomFrame(frame, _thread_name(tid, main_thread_id=mtid, current_thread_id=ctid), current_thread_id)

    info = current_thread.additionalInfo
    tb = dump.get('traceback')
    frames = []
    while tb:
        try:
            frame = tb.tb_frame
        except AttributeError:
            pass
        else:
            frames.insert(0, frame)
        try:
            tb = tb.tb_next
        except AttributeError:
            tb = None

    lines = ["", "Entering debugger for post mortem analysis of a Python heapdump."]

    if frames:
        try:
            formattedException = traceback.format_exception(dump['exception_class'], dump['exception'], dump['traceback'])

            lines.append("")
            lines.append('Exception information (stack displayed as "MainThread - pid...")')
            lines.extend(formattedException)
            lines.append("")
        except Exception:
            traceback.print_exc()

    lines.append("This is a POST MORTEM analysis: you can inspect variables in the call stack,")
    lines.append("but once you step or continue, the debugging terminates.")
    debugerWriteMsg(lines)

    if frames:
        frames_byid = {}
        tb = None
        frame = frames[0]
        while frame is not None:
            frames_byid[id(frame)] = frame
            frame = frame.f_back
        frame = frames[0]
        frames = None

        info.exception = (dump.get('exception_class'), dump.get('exception'), tb)
        info.pydev_force_stop_at_exception = (frame, frames_byid)
        info.message = "Exception from Python heapdump"
        debugger =pydevd.GetGlobalDebugger()
        # pydevd_tracing.SetTrace(None) #no tracing from here
        # pydev_log.debug('Handling post-mortem stop on exception breakpoint %s'% exception_breakpoint.qname)
        try:
            handle_post_mortem_stop = debugger.handle_post_mortem_stop
        except AttributeError:
            # Pydev versions up and including to 3.6.0
            debugger.force_post_mortem_stop += 1
        else:
            # Pydev versions since 3.7. Tested with 4.3.0
            from pydevd_tracing import SetTrace  # @UnresolvedImport
            SetTrace(None) # no tracing from here on. Otherwise we get a dead lock.
            handle_post_mortem_stop(info, current_thread)
    else:
        pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=True, trace_only_current_thread=True)


def debug_dump(dumpfile, dump=None, debugger_options=None, invoke_debugger_func=None):
    """
    Load and debug a Python heap dump

    This function loads and debugs a Python dump. First it calls :func:`load_dump` to
    load the dump and then it invokes a debugger to analyse the loaded dump.

    This function currently looks for the following debuggers in the given order.
    It uses the first debugger found:

     * :mod:`pydevd`, the debugger from the PyDev eclipse plugin. It requires PyDev version 3.3.3 or later and
       you must start the PyDev debug server in the debug perspective of eclipse.
     * :mod:`pdb`, the debugger from the Python library. Unfortunately, :mod:`pdb` supports neither
       threads nor tasklets.

    You can invoke this function directly from your shell::

        $ python -m pyheapdump --help

    Arguments

    :param dumpfile: the name of the heap-dump file or a file-like object open for reading bytes.
    :type dumpfile: str or file-like
    :param dump: The content of a heap-dump file (bytes) or
       a compressed pickle (bytes, starts with ``b"BZh9"``) or
       a MIME-message with content type ``application/x.python-heapdump``
       or the already unpickled heap dump dictionary. Exactly one of the two arguments *filename*
       and *dump* must be given.
    :type dump: bytes or :class:`~email.message.Message` or dict
    :param debugger_options: Subject to change. Intentionally not documented.
    :param invoke_debugger_func: Subject to change. Intentionally not documented.

    :returns: None
    """
    if debugger_options is None:
        debugger_options = {}
    if debugger_options.get('debugger_dir') is not None:
        sys.path.append(debugger_options['debugger_dir'])
    if invoke_debugger_func is None:
        if debugger_options.get('debugger') == 'pydevd':
            invoke_debugger_func = invoke_pydevd
        elif debugger_options.get('debugger') == 'pdb':
            invoke_debugger_func = invoke_pdb
        else:
            try:
                import pydevd  # @UnusedImport
            except ImportError:
                invoke_debugger_func = invoke_pdb
            else:
                invoke_debugger_func = invoke_pydevd

    dump = load_dump(dumpfile=dumpfile, dump=dump)
    invoke_debugger_func(dump, debugger_options)


def _tasklet_name(tasklet, tid, is_current=None, is_main=None, main_thread_id=None, current_thread_id=None):
    tl_prefix = ('', 'Main-', 'Current-', 'Main/Current-')[2 * bool(is_current) + bool(is_main)]
    try:
        tl_name = "'" + tasklet.name + "'"
    except AttributeError:
        tl_name = '%x' % (id(tasklet),)

    th_prefix = ('', 'Main-', 'Calling-', 'Main-/Calling-')[2 * (tid == current_thread_id) + (tid == main_thread_id)]

    return 'Dump: %sTasklet %s of %sthread %d' % (tl_prefix, tl_name, th_prefix, tid)


def _thread_name(tid, main_thread_id=None, current_thread_id=None):
    th_prefix = ('', 'Main-', 'Calling-', 'Main-/Calling-')[2 * (tid == current_thread_id) + (tid == main_thread_id)]

    return 'Dump: %sthread %d' % (th_prefix, tid)


def _cache_files(files):
    for name, data in files.iteritems():
        lines = [line + b'\n' for line in data.splitlines()]
        linecache.cache[name] = (len(data), None, lines, name)


class SurrogateState(object):
    def __init__(self, operation, exc=None, func=None, args=(), module=None, name=None):
        self.operation = operation
        self.exc = exc
        self.func = func
        self.args = args
        self.module = module
        self.name = name or "UNNAMED"

    def __getattr__(self, name):
        if name == '_list':
            self._list = l = []
            return l
        if name == '_dict':
            self._dict = d = {}
            return d
        raise AttributeError(name)


class AbstractSurrogate(object):
    def __new__(self, *args, **kw):
        assert isinstance(self, AbstractSurrogate)
        state = self._Surrogate__state
        try:
            cls = state._class
        except AttributeError:
            name = state.name or (type(self).__name__ + "Class")
            if isinstance(name, unicode):
                name = name.encode("UTF-8")
            module = state.module or __name__
            cls = type(name, (AbstractSurrogate,), dict(__module__=module))
            state._class = cls
        obj = object.__new__(cls)
        state = SurrogateState(operation="__new__", args=args)
        object.__setattr__(obj, "_Surrogate__state", state)
        obj.__setstate__(kw)
        return obj

    def __repr__(self):
        try:
            cls = self._Surrogate__state._class
        except AttributeError:
            return object.__repr__(self)
        return repr(cls)

    def __setitem__(self, key, value):
        cls = self.__class__
        cls.__bases__ = (SurrogatePersonalityDict, ) + cls.__bases__
        return SurrogatePersonalityDict.__setitem__(self, key, value)

    def __getattr__(self, name):
        if name in ('append', 'extend'):
            cls = self.__class__
            cls.__bases__ = (SurrogatePersonalityList, ) + cls.__bases__
            return getattr(self, name)
        if len(name) >= 5 and name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._Surrogate__state._state, name)

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self._Surrogate__state._state = state

    def __dir__(self):
        try:
            _state = self._Surrogate__state._state
        except AttributeError:
            return dir(self.__class__) + list(self.__dict__)
        else:
            return dir(_state)


# About the commented lines: I tried to turn the
# personalities into appropriate collections. This
# works fine, but the pydev debugger ignores this
# information. Perhaps we can reactivate this code later.
class SurrogatePersonalityDict(SurrogateState
                               # ,collections.Mapping
                               ):
    def __setitem__(self, key, value):
        self._Surrogate__state._dict[key] = value

#     def __len__(self):
#         return len(self._Surrogate__state._dict)
#
#     def __getitem__(self, index):
#         self._Surrogate__state._dict[index]
#
#     def __iter__(self):
#         return iter(self._Surrogate__state._dict)


class SurrogatePersonalityList(SurrogateState
                               # , collections.Sequence
                               ):
    def append(self, value):
        return self._Surrogate__state._list.append(value)

    def extend(self, sequence):
        return self._Surrogate__state._list.extend(sequence)

#     def __len__(self):
#         return len(self._Surrogate__state._list)
#
#     def __getitem__(self, index):
#         self._Surrogate__state._list[index]
#
#     def __iter__(self):
#         return iter(self._Surrogate__state._list)


def newUnpicklerSurrogate(operation, exc=None, func=None, args=(), module=None, name=None):
    if operation == "_instantiate" and isinstance(func, AbstractSurrogate):
        return func.__new__(func, *args)
    clsname = "ResultSurrogate_" + operation
    if isinstance(clsname, unicode):
        clsname = clsname.encode("UTF-8")
    d = {}
    if module:
        d['__module__'] = module
    cls = type(clsname, (AbstractSurrogate,), d)
    obj = object.__new__(cls)
    state = SurrogateState(operation=operation, exc=exc, func=func, args=args, module=module, name=name)
    object.__setattr__(obj, "_Surrogate__state", state)
    return obj


class FailSaveUnpickler(pickle.Unpickler):
    """A fail save unpickler
    """
    # make a copy of the global dispatch table
    # the unpickler uses self.dispatch to access the table
    dispatch = dict(pickle.Unpickler.dispatch)

    def on_exception(self, resolution):
        traceback.print_exc()
        print("Resolution: ", resolution, file=sys.stderr)

    def get_surrogate(self, operation, exc, func=None, args=(), module=None, name=None):
        if exc:
            self.on_exception("Created surrogate for operation " + operation)
        return newUnpicklerSurrogate(operation, exc, func=func, args=args, module=module, name=name)

    def _instantiate(self, klass, k):
        args = tuple(self.stack[k + 1:])
        del self.stack[k:]
        instantiated = 0
        if (not args and
                type(klass) is types.ClassType and  # @IgnorePep8
                not hasattr(klass, "__getinitargs__")):
            try:
                value = pickle._EmptyClass()
                value.__class__ = klass
                instantiated = 1
            except RuntimeError:
                # In restricted execution, assignment to inst.__class__ is
                # prohibited
                pass
        if not instantiated:
            try:
                value = klass(*args)
            except Exception, e:
                value = self.get_surrogate("_instantiate", exc=e, func=klass, args=args)
        self.append(value)

    def load_reduce(self):
        stack = self.stack
        args = stack.pop()
        func = stack[-1]
        try:
            value = func(*args)
        except Exception, e:
            value = self.get_surrogate("reduce", exc=e, func=func, args=args)

        stack[-1] = value
    dispatch[pickle.REDUCE] = load_reduce

    def load_newobj(self):
        args = self.stack.pop()
        cls = self.stack[-1]
        try:
            obj = cls.__new__(cls, *args)
        except Exception, e:
            obj = self.get_surrogate("newobj", exc=e, func=cls.__new__, args=(cls,) + args)
        self.stack[-1] = obj
    dispatch[pickle.NEWOBJ] = load_newobj

    def find_class(self, module, name):
        # Subclasses may override this
        try:
            __import__(module)
            mod = sys.modules[module]
            klass = getattr(mod, name)
        except Exception, e:
            klass = self.get_surrogate("find_class", e, module=module, name=name)
        return klass

    def load_build(self):
        stack = self.stack
        state = stack.pop()
        inst = stack[-1]
        try:
            setstate = getattr(inst, "__setstate__", None)
            if setstate:
                setstate(state)
                return
            slotstate = None
            if isinstance(state, tuple) and len(state) == 2:
                state, slotstate = state
            if state:
                try:
                    d = inst.__dict__
                    try:
                        for k, v in state.iteritems():
                            d[intern(k)] = v
                    # keys in state don't have to be strings
                    # don't blow up, but don't go out of our way
                    except TypeError:
                        d.update(state)

                except RuntimeError:
                    # XXX In restricted execution, the instance's __dict__
                    # is not accessible.  Use the old way of unpickling
                    # the instance variables.  This is a semantic
                    # difference when unpickling in restricted
                    # vs. unrestricted modes.
                    # Note, however, that cPickle has never tried to do the
                    # .update() business, and always uses
                    #     PyObject_SetItem(inst.__dict__, key, value) in a
                    # loop over state.items().
                    for k, v in state.items():
                        try:
                            setattr(inst, k, v)
                        except Exception:
                            self.on_exception("assignment ignored")
            if slotstate:
                for k, v in slotstate.items():
                    try:
                        setattr(inst, k, v)
                    except Exception:
                        self.on_exception("assignment ignored")
        except Exception:
            self.on_exception("assignments ignored")
    dispatch[pickle.BUILD] = load_build

DEFAULT_ON_UNHANDLED_EXCEPTION_MESSAGE = """Traceback (most recent call last):
{traceback}
{exctype.__name__}: {excvalue}

This program (or thread) terminated abnormal. A Python heap dump has been saved under:

  {dumpfile}

The developer of this program can use the dump to analyse the failure.
"""


def dump_on_unhandled_exceptions(function=None, dump_dir=None, message=None, files=None,
                                 reraise=None, daisy_chain_sys_excepthook=None):
    """
    Create a heap dump for each unhandled exception.

    This function acts as a function decorator or, if no function is given,
    registers a :attr:`sys.excepthook` handler. In both cases it causes python to
    create heap dumps on otherwise unhandled exceptions.

    If *function* is given, dump_on_unhandled_exceptions wraps *function*
    and returns the newly created wrapper. The wrapper catches exceptions
    of type :exc:`Exception` and writes a heap dump. If *reraise* is true,
    it re-raises the exception. Otherwise it returns `None`.

    If *function* is `None`, dump_on_unhandled_exceptions registers a
    :attr:`sys.excepthook` handler. If the handler receives an :exc:`Exception`,
    it writes a heap dump. If *daisy_chain_sys_excepthook* is true, the
    handler finally calls the previous exception handler.

    :param function: a callable. If given dump_on_unhandled_exceptions returns a wrapper for *function*.
    :param dump_dir: the directory where to create the dump. If
      set to `None`, the dump is created in the directory given by
      the environment variable :envvar:`PYHEAPDUMP_DIR` or, if the variable
      is unset or empty, the dump is created in the directory returned by
      :func:`tempfile.gettempdir()`.
    :type dump_dir: a string.
    :param message: a message to print on sys.stderr.
    :type message: string
    :param files: this argument controls, if the heap dump contains the source code of those Python files, that contribute
        to the dumped frames. If *files* is `None` and
        the environment variable :envvar:`PYHEAPDUMP_WITH_FILES` is defined, *files* is set from PYHEAPDUMP_WITH_FILES
        as follows: if PYHEAPDUMP_WITH_FILES contains :attr:`os.path.pathsep`, *files* is set to the list of
        path entries. Otherwise, *files* is set to `True` if PYHEAPDUMP_WITH_FILES is "yes" or "true". All other non empty
        values set *files* to `False`.

        If *files* is a container, a file is included, if its name is in the container. Otherwise, if *files* is a
        callable, it will be called with a file name as its single argument. If the callable returns a true-value, the file
        will be included. Otherwise, if *files* is a true-value, all files are included. Lastly, if *files* is `None`, a default
        behaviour applies which is currently to include all files.
    :param reraise: if true, a wrapper re-raises the caught exception.
    :type reraise: bool
    :param daisy_chain_sys_excepthook: if true, daisy chain the original sys.excepthook handler.
    :type daisy_chain_sys_excepthook: bool
    """
    if message is None:
        message = DEFAULT_ON_UNHANDLED_EXCEPTION_MESSAGE

    if dump_dir is None:
        dump_dir = os.environ.get("PYHEAPDUMP_DIR")
        if dump_dir and dump_dir.lower() == "disable":
            return function

    if dump_dir is not None and not os.path.isdir(dump_dir):
        dump_dir = None
    if not dump_dir:
        dump_dir = tempfile.gettempdir()
    dump_dir = os.path.abspath(dump_dir)

    if files is None:
        files = os.environ.get("PYHEAPDUMP_WITH_FILES")
        if files:
            if os.path.pathsep in files:
                files = files.split(os.path.pathsep)
            else:
                files = files.lower() in ('yes', 'true', 'y')
        else:
            files = None

    filename = os.path.basename('python_heap_' + str(os.getpid())) + '_{sequence_number}' + os.path.extsep + 'dump'
    name_and_path = os.path.join(dump_dir, filename)

    if function is not None:
        # Used as a decorator/wrapper
        @functools.wraps(function)
        def _dump_on_unhandled_exceptions_wrapper(*args, **kw):
            try:
                return function(*args, **kw)
            except Exception:
                try:
                    try:
                        lf = lock_function()
                        exctype, value, traceback_ = sys.exc_info()
                        name_and_path2 = save_dump(name_and_path, exc_info=(exctype, value, traceback_),
                                                   files=files, lock_function=lf)[0]
                        if message:
                            print(message.format(exctype=exctype, excvalue=value,
                                                 traceback="".join(traceback.format_tb(traceback_))[:-1],
                                                 dumpfile=name_and_path2, dump_dir=dump_dir,
                                                 dump_base_name=filename),
                                  file=sys.stderr)
                    except Exception:
                        traceback.print_exc()
                finally:
                    if reraise:
                        raise
        return _dump_on_unhandled_exceptions_wrapper

    # set sys.exepthook
    orig_excepthook = sys.excepthook

    def excepthook(exctype, value, traceback_):
        if isinstance(value, Exception):
            with atomic():
                ok = False
                sys.excepthook = orig_excepthook
                try:
                    name_and_path2 = save_dump(name_and_path, exc_info=(exctype, value, traceback_), files=files)[0]
                    ok = True
                finally:
                    sys.excepthook = excepthook
            if ok and message:
                print(message.format(exctype=exctype, excvalue=value,
                                     traceback="".join(traceback.format_tb(traceback_))[:-1],
                                     dumpfile=name_and_path2, dump_dir=dump_dir,
                                     dump_base_name=filename),
                      file=sys.stderr)
        if daisy_chain_sys_excepthook and callable(orig_excepthook):
            orig_excepthook(exctype, value, traceback)
    sys.excepthook = excepthook
    return None
