# Copyright 2017 Janos Czentye
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Contains functions and classes for remote visualization.
"""
import os
import shutil
import threading
import time

import wrapt
from flask import logging

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__) + "/../")
log = logging.getLogger("trail")


class Singleton(type):
  """
  Metaclass for classes need to be created only once.

  Realize Singleton design pattern in a pythonic way.
  """
  _instances = {}

  def __call__ (cls, *args):
    """
    Override.
    """
    if cls not in cls._instances:
      cls._instances[cls] = super(Singleton, cls).__call__(*args)
    return cls._instances[cls]


class MessageDumper(object):
  __metaclass__ = Singleton
  DIR = "log/trails/"
  __lock = threading.Lock()

  def __init__ (self):
    self.__cntr = 0
    self.__clear_trails()
    self.__init()

  @wrapt.synchronized(__lock)
  def increase_cntr (self):
    self.__cntr += 1
    return self.__cntr

  def __init (self):
    self.log_dir = self.DIR + time.strftime("%Y%m%d%H%M%S")
    for i in xrange(1, 10):
      if not os.path.exists(os.path.join(PROJECT_ROOT, self.log_dir)):
        os.mkdir(os.path.join(PROJECT_ROOT, self.log_dir))
        break
      else:
        self.log_dir += "+"
    else:
      log.warning("Log dir: %s has already exist for given timestamp prefix!")

  def __clear_trails (self):
    log.debug("Remove trails...")
    for f in os.listdir(os.path.join(PROJECT_ROOT, self.DIR)):
      if f != ".placeholder" and not f.startswith(time.strftime("%Y%m%d")):
        # os.remove(os.path.join(PROJECT_ROOT, self.log_dir, f))
        shutil.rmtree(os.path.join(PROJECT_ROOT, self.DIR, f),
                      ignore_errors=True)

  def dump_to_file (self, data, unique):
    if not isinstance(data, basestring):
      log.error("Data is not str: %s" % type(data))
      return
    trails = os.path.join(PROJECT_ROOT, self.log_dir)
    date = time.strftime("%Y%m%d%H%M%S")
    cntr = self.increase_cntr()
    file_path = os.path.join(trails,
                             "%s_%03d_%s.log" % (date, cntr, unique))
    if os.path.exists(file_path):
      log.warning("File path exist! %s" % file_path)
    log.debug("Logging data to file: %s..." % file_path)
    with open(file_path, "w") as f:
      f.write(data)
