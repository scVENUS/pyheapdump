pyheapdump
==========

Post-mortem debugging for Python. 

Documentation
-------------

Please read the source or create the html-documentation using the following command:

```python setup.py build_sphinx```


Acknowledgement and Previous Work
---------------------------------

This Python extension is based on the Pydump (https://github.com/gooli/pydump), a Python extension written 
and published by Eli Finer. During the development of pyheapdump my code diverged from 
Eli's work to a point where nearly no common code was left. I decided, to rename my work to
pyheapdump in order to make it clear, that it is now a separate project. 


Changelog
---------

2015-08-25 Version 0.2.5:

 * Support Pydev versions 3.7 and up (tested with version 4.3.0).

2014-07-25 Version 0.2.4:

 * Fix a trivial bug introduced in 0.2.3: crash, if PYHEAPDUMP_DIR is unset.

2014-07-25 Version 0.2.3:

 * Rewrote the unpickle surrogate mechanism.
   Now the surrogate classes resemble the original classes
   and support operations used during unpickling.

 * Setting the environmnet variable PYHEAPDUMP_DIR to "disable"
   disables pyheapdump.

 * Pydevd only: print the exception to the debugger console.

2014-07-13 Version 0.2.2:

 * Add an option to control the inclusion of python source into the dump.
   If you use dump_on_unhandled_exceptions you can use the environment 
   variable PYHEAPDUMP_WITH_FILES=no to exclude files. Read the documentation
   of dump_on_unhandled_exceptions for additional options.
   
 * If you use PyDev to analyse a dump and a python source file is not available,
   PyDev now extracts the source from the dump. (Eventually you have to enable
   the action "Get from server (read only)" in the PyDev Source Locator preferences:
   Menu "Window" -> "Preferences" -> "PyDev" -> "Run/Debug" -> "Source Locator" ->
   "Action when source is not directly found".)

2014-07-12 Version 0.2.1:

 * Work around Python bug http://bugs.python.org/issue21967. It used to 
   crash the Python interpreter under certain conditions.

 * Added examples in the directory examples.

 * Added a lock to prevent simultaneous dumps from multiple threads.
   Function save_dump now returns the file name and the headers.
   If the file name comtains the sub-string '{sequence_number}',
   it is replaced by the running number of the dump.

 * New function dump_on_unhandled_exceptions. It can be used as a 
   function decorator or to setup a sys.execpthook handler. The environment
   variable PYHEAPDUMP_DIR defines the dump directory.

 * Rewrite of the thread/tasklet locking to avoid dead locks.

 * Disable logging during the creation of the pickle. This prevents secondary errors, if
   the log system is the cause of heap dump. Requires a new sPickle package.

 * Improved readability of the dump file format.

 * New command line interface. See "python -m pyheapdump --help" for details.

 * Work around for Stackless bug #61 while unpickling heap dumps. Previously Stackless
   used to crash, if you inspect the local variables of certain frames.

2014-05-09 Version 0.2:
 * New dump file format (RFC 2045 MIME-message, content type 'application/x.python-heapdump').

2014-02-11 Version 0.1.1:

 * Updated documentation
 * Minor API extensions

