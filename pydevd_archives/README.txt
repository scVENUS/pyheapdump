This directory contains several versions of the PyDev Python code.

The test case pyheapdump.test_pyheapdump.PyheapdumpTest.testDebugDump uses
these archives to test the compatibility with several versions of pydevd.

You can create the archives using the following command in a PyDev sandbox
cloned from https://github.com/fabioz/Pydev.git

$ for VERSION in 3_6_0 3_7_0 4_4_0 4_5_0; do
>    git archive --format=zip -o /path/to/pyheapdump/pydevd_archives/pydev_${VERSION}.zip pydev_${VERSION}:plugins/org.python.pydev/pysrc
> done
