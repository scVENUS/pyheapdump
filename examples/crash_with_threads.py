
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
import random
import operator
import time

import pyheapdump
# pyheapdump.dump_on_unhandled_exceptions()


@pyheapdump.dump_on_unhandled_exceptions
def worker(shared_storage, index, condition):
    while True:
        v = shared_storage[0] + 1
        sys.stdout.write("Worker {} {}\n".format(index, v))
        if index:
            if v % condition == index:
                raise ValueError("Exception!!!")
        shared_storage[0] = v


def main(argv):
    n_threads = 3
    shared_storage = [1]
    condition = 100
    for i in range(n_threads):
        t = threading.Thread(args=(shared_storage, i, condition), target=worker)
        t.daemon = True
        t.start()
    count = threading.active_count()
    last_count = count
    while(count >= last_count):
        last_count = count
        count = threading.active_count()
        #print("values: ", shared_storage)
        time.sleep(0.5)

    print ("Opps, a thread died.")

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
