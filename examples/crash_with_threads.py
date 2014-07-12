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

import threading
import sys
import time
import Queue

import pyheapdump
pyheapdump.dump_on_unhandled_exceptions()


@pyheapdump.dump_on_unhandled_exceptions
def worker(index, condition, input_data_source, result_queue):
    for input_data in input_data_source:
        result = input_data + 1  # really complicated and time consuming computation
        # unfortunately the algorithm is error prone ;-)
        if condition == 0 or (input_data > 10 and input_data % condition == index):
            raise ValueError("Exception!!!")
        time.sleep(0.1)

        # store the result
        result_queue.put("Worker {} input_data {} result {}".format(index, input_data, result))


def main(argv):
    """Run the example

    Usage::

        python crash_with_threads.py [<number of threads> [<condition>]]

        number of threads: the number of worker threads
    """
    n_threads = int(argv.pop(0)) if argv else 3
    condition = int(argv.pop(0)) if argv else 20
    sys.setcheckinterval(1000)
    input_data_source = iter(xrange(sys.maxint))
    result_queue = Queue.Queue()
    all_threads = []
    for i in range(n_threads):
        t = threading.Thread(args=(i, condition, input_data_source, result_queue), target=worker)
        t.daemon = True
        all_threads.append(t)
    for t in all_threads:
        t.start()
    t = all_threads = None
    last_count = count = n_threads
    while(count >= last_count):
        last_count = count
        count = threading.active_count()
        try:
            result = result_queue.get(block=False, timeout=0.5)
        except Queue.Empty:
            if condition == 42:
                raise
        else:
            print("Result: ", result)

    print ("Opps, a thread died.")

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
