###############################################################################
#   lazyflow: data flow based lazy parallel computation framework
#
#       Copyright (C) 2011-2014, the ilastik developers
#                                <team@ilastik.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the Lesser GNU General Public License
# as published by the Free Software Foundation; either version 2.1
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# See the files LICENSE.lgpl2 and LICENSE.lgpl3 for full text of the
# GNU Lesser General Public License version 2.1 and 3 respectively.
# This information is also available on the ilastik web site at:
#		   http://ilastik.org/license/
###############################################################################

from abc import abstractmethod, ABCMeta

#lazyflow
from lazyflow.graph import Operator
from lazyflow.operators.cacheMemoryManager import CacheMemoryManager


class OpCache(Operator):
    """
    Interface for operators that act as caches

    This interface is designed for operators that hold values but can neither
    be queried for their memory usage nor be cleaned up. All operators that
    have non-negligible amounts of memory allocated internally *must* implement
    this interface. However, most operators that need to implement this
    interface *should* probably implement an extended interface (see below).
    This interface can still be useful for several purposes:
      * tell the user about memory consuming objects in general (e.g. in an
        environment like ilastik)
      * automated statistics and tests

    Caches are automatically added to the CacheMemoryManager instance.
    """

    __metaclass__ = ABCMeta

    def generateReport(self, memInfoNode):
        rs = []
        for child in self.children:
            if not isinstance(child, OpCache):
                continue
            r = MemInfoNode()
            child.generateReport(r)
            rs.append(r)
        memInfoNode.children = rs
        memInfoNode.type = type(self)
        memInfoNode.id = id(self)
        memInfoNode.name = self.name

    def _after_init(self):
        """
        Overridden from Operator to add us to the cache management
        """
        super(OpCache, self)._after_init()

        # Register with the manager here, AFTER we're fully initialized
        # Otherwise it isn't safe for the manager to poll our stats.
        manager = CacheMemoryManager()
        if self.parent is None or not isinstance(self.parent, OpCache):
            manager.addFirstClassCache(self)
        else:
            manager.addCache(self)


class OpObservableCache(OpCache):
    """
    Interface for caches that can report their usage

    This interface is intended for caches that can be measured, but for
    which no (easy) cleanup method is known, or which do not want to
    be cleaned up by the cache memory manager. 
    """

    @abstractmethod
    def usedMemory(self):
        """
        get used memory in bytes of this cache and all observable children
        """
        total = 0
        for child in self.children:
            if isinstance(child, OpObservableCache):
                total += child.usedMemory()
        return 0

    @abstractmethod
    def fractionOfUsedMemoryDirty(self):
        """
        get fraction of used memory that is in a dirty state

        Dirty memory is memory that has been allocated, but cannot be used
        anymore. It is ok to always return 0 if there is no dirtiness
        management inside the cache. The returned value must lie in the
        range [0, 1].
        """
        return 0.0

    def generateReport(self, memInfoNode):
        super(OpObservableCache, self).generateReport(memInfoNode)
        memInfoNode.usedMemory = self.usedMemory()
        memInfoNode.fractionOfUsedMemoryDirty =\
            self.fractionOfUsedMemoryDirty()


class OpManagedCache(OpObservableCache):
    """
    Interface for caches that can report their usage and can be cleaned up
    """

    _last_access_time = 0.0

    @abstractmethod
    def lastAccessTime(self):
        """
        get the timestamp of the last access (python timestamp)

        In general, time.time() should be used here. Don't be afraid to use the
        default implementation, i.e. fill the attribute _last_access_time.
        """
        return self._last_access_time

    @abstractmethod
    def freeMemory(self):
        """
        free all memory cached by this operator and its children

        The result of `freeMemory()` should be compatible with
        `usedMemory()`, i.e.

        >>> a = cache.usedMemory()
        >>> d = cache.freeMemory()
        >>> a - d == cache.usedMemory()
        True  

        @return amount of bytes freed (if applicable)
        """
        raise NotImplementedError("No default implementation for freeMemory()")

    def generateReport(self, memInfoNode):
        super(OpManagedCache, self).generateReport(memInfoNode)
        memInfoNode.lastAccessTime = self.lastAccessTime()


class MemInfoNode:
    """
    aggregation of cache status indicators
    """
    # type
    type = None

    # object id
    id = None

    # used memory in bytes
    usedMemory = None

    # data type of single cache elements (if applicable)
    dtype = None

    # a region of interest this cache is assigned to
    # (mostly useful for wrapped caches as in OpBlockedArrayCache)
    roi = None

    # fraction of used memory that is dirty
    fractionOfUsedMemoryDirty = None

    # python timestamp of last access
    lastAccessTime = None

    # operator name
    name = None

    # additional info set by cache implementation
    info = None

    # reports for all of this operators children that are of type
    # OpObservableCache
    children = None

    def __init__(self):
        self.children = list()
