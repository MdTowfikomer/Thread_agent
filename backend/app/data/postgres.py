"""Bounded per-process connection reuse; authorization stays in fresh SQL reads.

Leases close their cursors, roll back unfinished transactions and return connections
to a thread-safe pool. Dedicated advisory-lock connections must not use this helper.
"""
import atexit
import os
import threading
import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.pool import ThreadedConnectionPool

DEFAULT_OPTIONS = '-c statement_timeout=10000 -c lock_timeout=5000'
_pools = {}
_lock = threading.Lock()


class DatabaseUnavailableError(RuntimeError):
    pass


class _Pool:
    def __init__(self, url, connect_timeout, options):
        maximum = max(1, min(16, int(os.getenv('THREAD_DB_POOL_MAX_CONNECTIONS', '4'))))
        self.slots = threading.BoundedSemaphore(maximum)
        self.pool = ThreadedConnectionPool(1, maximum, dsn=url, connect_timeout=connect_timeout, options=options)


class _Lease:
    def __init__(self, owner, connection):
        self._owner = owner
        self._connection = connection
        self._released = False
        self._cursors = []

    def _check_open(self):
        if self._released:
            raise psycopg2.InterfaceError('connection lease is closed')

    @property
    def closed(self):
        return self._released or self._connection.closed

    @property
    def autocommit(self):
        self._check_open()
        return self._connection.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._check_open()
        self._connection.autocommit = value

    def __getattr__(self, name):
        self._check_open()
        return getattr(self._connection, name)

    def cursor(self, *args, **kwargs):
        self._check_open()
        cursor = self._connection.cursor(*args, **kwargs)
        self._cursors.append(cursor)
        return cursor

    def __enter__(self):
        self._check_open()
        self._connection.__enter__()
        return self

    def __exit__(self, *args):
        try:
            return self._connection.__exit__(*args)
        finally:
            self.close()

    def close(self):
        if self._released:
            return
        self._released = True
        discard = bool(self._connection.closed)
        try:
            for cursor in self._cursors:
                try:
                    cursor.close()
                except Exception:
                    discard = True
            if not discard and self._connection.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                self._connection.rollback()
            if not discard and self._connection.autocommit:
                self._connection.autocommit = False
        except Exception:
            discard = True
        try:
            self._owner.pool.putconn(self._connection, close=discard)
        finally:
            self._owner.slots.release()


def connect(url, *, connect_timeout=5, options=DEFAULT_OPTIONS):
    if os.getenv('THREAD_DB_POOL_ENABLED', 'true').lower() in {'0', 'false', 'no'}:
        return psycopg2.connect(url, connect_timeout=connect_timeout, options=options)
    key = (os.getpid(), url, connect_timeout, options)
    try:
        with _lock:
            owner = _pools.get(key)
            if owner is None:
                owner = _Pool(url, connect_timeout, options)
                _pools[key] = owner
        wait = max(0.01, min(30, float(os.getenv('THREAD_DB_POOL_WAIT_SECONDS', '5'))))
        if not owner.slots.acquire(timeout=wait):
            raise DatabaseUnavailableError('Database connection capacity is temporarily unavailable.')
        try:
            connection = owner.pool.getconn()
            return _Lease(owner, connection)
        except Exception:
            owner.slots.release()
            raise
    except Exception:
        # Never include the DSN or original driver exception chain in diagnostics.
        raise DatabaseUnavailableError('Database connection is temporarily unavailable.') from None


def close_pools():
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for owner in pools:
        owner.pool.closeall()


atexit.register(close_pools)
