#
# Copyright 2012-2014 "Korora Project" <dev@kororaproject.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the temms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import multiprocessing
import time

from Lens.View import EventEmitter

__counter = 0
def _new_name():
  global __counter
  __counter += 1
  return "LensThread-{}-{}".format(__counter, time.time())



class Thread(EventEmitter):
  def __init__(self):
    EventEmitter.__init__(self)

    # the ID won't change when the name changes
    self._uuid = _new_name()

  @property
  def uuid(self):
    return self._uuid

  def run(self):
    pass



class ThreadProcess(multiprocessing.Process):
  def __init__(self, thread, pipe_in, queue_out):
    multiprocessing.Process.__init__(self)

    self._thread = thread
    self._uuid = thread.uuid

    self.daemon = True

    self._thread.on_any(self._thread_signal_cb)

    self._pipe_in = pipe_in
    self._queue_out = queue_out

  def _thread_signal_cb(self, name, *args):
    self._queue_out.put({
      'uuid': self.uuid,
      'name': name,
      'args': list(args)
    })

  @property
  def uuid(self):
    return self._uuid

  def run(self):

    self._thread.run()

    self._queue_out.put({
      'uuid': self.uuid,
      'name': '__completed'
    })



class ThreadManager(EventEmitter):
  """
  Manages many LensThreads. This involves starting and stopping
  said threads, and respecting a maximum num of concurrent threads limit
  """
  def __init__(self, maxConcurrentThreads=5):
    EventEmitter.__init__(self)

    #stores all threads, running or stopped
    self.threads = {}
    self.pendingThreadArgs = []
    self.maxConcurrentThreads = maxConcurrentThreads

    self.queue_in = multiprocessing.Queue()


  def _thread_completed(self, thread):
    """
    Decrements the count of concurrent threads and starts any
    pending threads if there is space
    """
    del(self.threads[thread.uuid])
    running = len(self.threads) - len(self.pendingThreadArgs)

    print("%s completed. %s running, %s pending" % (thread, running, len(self.pendingThreadArgs)))

    if running < self.maxConcurrentThreads:
      try:
        uuid = self.pendingThreadArgs.pop()
        print("Starting pending %s" % self.threads[uuid])
        self.threads[uuid]['t'].start()
      except IndexError:
        pass

  def _register_thread_signals(self, thread, *args):
    pass

  def add_thread(self, thread):
    # TODO: be nicer
    if not isinstance(thread, Thread):
      raise TypeError("not a LensThread stupiD!")

    running = len(self.threads) - len(self.pendingThreadArgs)

    _pipe = None
    _thread = ThreadProcess(thread, _pipe, self.queue_in)

    uuid = _thread.uuid

    if uuid not in self.threads:
      self.threads[uuid] = {
        't': _thread,
        'p': _pipe
      }

      self._register_thread_signals(_thread)

      if running < self.maxConcurrentThreads:
        print("Starting %s" % _thread)
        self.threads[uuid]['t'].start()

      else:
        print("Queing %s" % thread)
        self.pendingThreadArgs.append(uuid)


  def on_thread(self, thread, name, callback):
    self.on('__thread_%s_%s' % (name, thread.uuid), callback)
