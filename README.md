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

2014-xx-xx Version 0.x:
 * Added a lock to prevent simultaneous dumps from multiple threads.
   Function save_dump now returns the file name and the headers.
   If the file name comtains the sub-string '{sequence_number}',
   it is replaced by the running number of the dump.

 * New function dump_on_unhandled_exceptions. It can be used as a 
   function decorator or to setup a sys.execpthook handler.

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

