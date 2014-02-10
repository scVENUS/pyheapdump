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
__all__ = ('save_dump', 'create_dump', 'load_dump', 'debug_dump')

import os
import sys
import types
import thread
import threading
import collections
import sPickle
import pickle
import linecache
import inspect
import contextlib
import traceback
import weakref

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
        old = sys.getcheckinterval()
        sys.setcheckinterval(sys.maxint)
        try:
            yield
        finally:
            sys.setcheckinterval(old)

    @contextlib.contextmanager
    def block_trap():
        try:
            yield
        finally:
            pass

else:
    isStackless = True

    taskletType = stackless.tasklet
    atomic = stackless.atomic

    def run_in_tasklet(func, *args, **kw):
        current = stackless.current
        result = []

        def call_func():
            try:
                result.append(func(*args, current_tasklet=current, **kw))
            except Exception:
                exc_info = sys.exc_info()
                current.throw(exc=exc_info[0], val=exc_info[1], tb=exc_info[2])
            else:
                current.switch()
        result.append(stackless.tasklet())
        result[0].set_atomic(True)
        result.pop().bind(call_func, ()).switch()
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


def save_dump(filename, tb=None, exc_info=None, threads=None, tasklets=None):
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
    :returns: `None`.
    """
    with atomic():
        if tb is not None and exc_info is None:
            exc_info = (None, None, tb)
        dump = create_dump(exc_info=exc_info, threads=threads, tasklets=tasklets)
        with open(filename, 'wb') as f:
            f.write(dump)


def create_dump(exc_info=None, threads=None, tasklets=None):
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
        returned by :func:`sys.exc_info` will be used. If set to `True`, :func:`save_dump` does not add
        exception information to the dump.
    :param threads: A single thread id (type is `int`) or a sequence of thread ids (type is :class:`collections.Sequence`)
        or `None` for all threads (default) or `False` to omit thread information altogether.
    :param tasklets: Stackless Python only: either `None` for all tasklets (default) or `False` to omit tasklet information altogether.
    :returns: the compressed pickle of the dump.
    :rtype: str
    """
    with atomic(), high_recusion_limit():
        return run_in_tasklet(_create_dump_impl, exc_info=exc_info, threads=threads, tasklets=tasklets)


def _create_dump_impl(exc_info=None, threads=None, tasklets=None, current_tasklet=None):
    """
    Implementation of :func:`create_dump`.
    """
    with atomic(), high_recusion_limit():
        files = {}
        dump = {'dump_version': DUMP_VERSION, 'files': files}
        # add exception information
        if exc_info is not False:
            if exc_info is None:
                exc_info = sys.exc_info()
            dump['exception_class'] = exc_info[0]
            dump['exception'] = exc_info[1]
            dump['traceback'] = exc_info[2]
            _get_traceback_files(exc_info[2], files=files)

        # add threads
        current_thread_id = thread.get_ident()
        dump['current_thread_id'] = current_thread_id
        dump['main_thread_id'] = main_thread_id()

        current_frames = sys._current_frames()
        if threads is True:
            threads = current_frames.keys()
        elif isinstance(threads, int):
            threads = [threads]
        elif isinstance(threads, (list, tuple, collections.Sequence)):
            threads = list(threads)

        # add tasklets
        if isStackless and tasklets is not False:
            dump['tasklets'] = _collect_tasklets(current_tasklet, threads)
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
                    thread_frames[tid] = frame
                    _get_frame_files(frame, files)
                    # del frame
            del thread_frames
        del current_frames
        del exc_info

        try:
            del files
            # pickle
            pt = sPickle.SPickleTools(pickler_class=DumpPickler)
            with block_trap():
                return pt.dumps(dump)
        finally:
            dump.clear()


def _collect_tasklets(current_tasklet, threads):
    taskletType = stackless.tasklet
    this_tasklet = stackless.current
    tasklets = {}
    for tid in threads:
        main, current, runcount = stackless.get_thread_info(tid)

        #
        # find scheduled tasklets
        #
        t = current.next
        if current is this_tasklet:
            current = current_tasklet

        assert current is not this_tasklet
        assert main is not this_tasklet

        other = {id(current): current}
        other[id(main)] = main
        while t is not None and t is not this_tasklet:
            oid = id(t)
            if oid in other:
                break
            other[oid] = t
            t = t.next

        #
        # Here we could look at other tasklet-holders too
        #

        tasklets[tid] = (main, current, other)
    return tasklets


class DumpPickler(sPickle.FailSavePickler):

    def __init__(self, *args, **kw):
        self.__class__.__bases__[0].__init__(self, *args, **kw)
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
        if tasklet is stackless.current:
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
    def __init__(self, repr, vars):
        self.__repr = repr
        self.__dict__.update(vars)

    def __repr__(self):
        return self.__repr


class FakeFrame(object):
    __slots__ = ('f_back', 'f_builtins', 'f_code', 'f_exc_traceback', 'f_exc_type', 'f_exc_value',
                 'f_globals', 'f_lasti', 'f_lineno', 'f_locals', 'f_restricted', 'f_trace')

    @classmethod
    def for_frame(cls, frame, memo):
        if frame is None:
            return None
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
            fake_frame.f_restricted = frame.f_restricted
            fake_frame.f_trace = frame.f_trace
            return fake_frame


class FakeTraceback(object):
    __slots__ = ('tb_frame', 'tb_lasti', 'tb_lineno', 'tb_next')

    @classmethod
    def for_tb(cls, traceback, memo):
        if traceback is None:
            return None
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


def _get_traceback_files(traceback, files=None):
    if files is None:
        files = {}
    while traceback:
        _get_frame_files(traceback.tb_frame, files)
        traceback = traceback.tb_next
    return files


def _get_frame_files(frame, files):
    while frame:
        filename = os.path.abspath(frame.f_code.co_filename)
        if filename not in files:
            try:
                files[filename] = open(filename).read()
            except IOError:
                files[filename] = "couldn't locate '%s' during dump" % frame.f_code.co_filename
        frame = frame.f_back
    return files


def _safe_repr(v):
    try:
        return repr(v)
    except Exception, e:
        return "repr error: " + str(e)


def load_dump(filename=None, dump=None):
    """
    Load a Python heap dump

    This function loads and preprocesses a Python dump file or
    a python dump string or an already unpickled heap dump dictionary.

    Arguments

    :param filename: the filename of the heap-dump file.
    :type filename: str
    :param dump: The pickled and compressed dump as a byte string or the already
       unpickled heap dump dictionary. Exactly one of the two arguments *filename*
       and *dump* must be given.
    :type dump: str or dict
    :returns: the preprocessed heap dump dictionary
    :rtype: dict
    """
    if dump is None:
        with open(filename, 'rb') as f:
            dump = f.read()
    if isinstance(dump, str):
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


def debug_dump(dump_filename, dump=None, post_mortem_func=None):
    """
    Load and debug a Python heap dump

    This function loads and debugs a Python dump. First it calls :func:`load_dump` to
    load the dump and then it invokes a debugger to analyse the loaded dump.

    This function currently looks for the following debuggers in the given order.
    It uses the first debugger found:

     * :mod:`pydevd`, the debugger from the PyDev eclipse plugin. Use version 3.3.3 or later and
       run the remote debug server.
     * :mod:`pdb`, the debugger from the Python library. Unfortunately, :mod:`pdb` supports neither
       threads nor tasklet.

    You can invoke this function directly from your shell::

        $ python -m pyheapdump mydumpfile.pydump

    Arguments

    :param filename: the filename of the heap-dump file.
    :type filename: str
    :param dump: The pickled and compressed dump as a byte string or the already
       unpickled heap dump dictionary. Exactly one of the two arguments *filename*
       and *dump* must be given.
    :type dump: str or dict
    :param post_mortem_func: Subject to change. Intentionally not documented.
    :returns: the preprocessed heap dump dictionary
    :rtype: dict
    """
    if post_mortem_func is None:
        try:
            import pydevd
            from pydevd_custom_frames import addCustomFrame
        except ImportError:
            import pdb
            post_mortem_func = lambda d: pdb.post_mortem(d['traceback'])
        else:
            def post_mortem_func(dump):
                current_thread_id = thread.get_ident()
                current_thread = threading.current_thread()
                pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=False, trace_only_current_thread=True)

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
                        for oid, tasklet in value[2].iteritems():
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

                if frames:
                    frames_byid = {}
                    tb = None
                    frame = frames[0]
                    while frame is not None:
                        frames_byid[id(frame)] = frame
                        frame = frame.f_back
                    frame = frames[0]
                    frames = None

                    info.pydev_force_stop_at_exception = (frame, frames_byid)
                    pydevd.GetGlobalDebugger().force_post_mortem_stop += 1
                else:
                    pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=True, trace_only_current_thread=True)

    return _debug_dump_impl(dump_filename, dump, post_mortem_func)


def _debug_dump_impl(dump_filename, dump, post_mortem_func):
    dump = load_dump(filename=dump_filename, dump=dump)
    _cache_files(dump['files'])
    _old_checkcache = linecache.checkcache
    linecache.checkcache = lambda filename = None: None
    post_mortem_func(dump)
    linecache.checkcache = _old_checkcache


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


class UnpicklerSurrogate(object):
    def __init__(self, operation, exc, func=None, args=(), module=None, name=None):
        self.operation = operation
        self.exc = exc
        self.func = func
        self.args = args
        self.module = module
        self.name = name


class FailSaveUnpickler(pickle.Unpickler):
    dispatch = pickle.Unpickler.dispatch

    def on_exception(self, resolution):
        traceback.print_exc()
        print("Resolution: ", resolution, file=sys.stderr)

    def get_surrogate(self, operation, exc, func=None, args=(), module=None, name=None):
        if exc:
            self.on_exception("Created surrogate for operation " + operation)
        return UnpicklerSurrogate(operation, exc, func=func, args=args, module=module, name=name)

    def _instantiate(self, klass, k):
        args = tuple(self.stack[k + 1:])
        del self.stack[k:]
        instantiated = 0
        if (not args and
                type(klass) is types.ClassType and
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
