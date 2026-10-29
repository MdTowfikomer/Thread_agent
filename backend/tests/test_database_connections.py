"""Connection reuse must retain fresh transactions, cleanup and bounded concurrency."""
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from app.tenancy.repository import TenantRepository


@pytest.fixture
def database(monkeypatch):
    module=sys.modules.get('app.data.postgres')
    if module: module.close_pools()
    monkeypatch.setenv('THREAD_DB_POOL_ENABLED','true')
    monkeypatch.setenv('THREAD_DB_POOL_MAX_CONNECTIONS','2')
    monkeypatch.setenv('THREAD_DB_POOL_WAIT_SECONDS','0.05')
    monkeypatch.setenv('THREAD_SERVICE_DB_URL','postgresql://synthetic-pool-test')
    connections=[]
    def connect(*a,**kw):
        conn=MagicMock();conn.closed=0;conn.autocommit=False
        conn.get_transaction_status.return_value=0
        conn.__enter__.return_value=conn
        connections.append(conn)
        return conn
    monkeypatch.setattr('psycopg2.connect',connect)
    yield TenantRepository(),connections
    module=sys.modules.get('app.data.postgres')
    if module:module.close_pools()


def test_sequential_transactions_reuse_connection_and_close_cursors(database):
    repository,connections=database
    for _ in range(3):
        with repository.transaction() as cur:cur.execute('SELECT 1')
    assert len(connections)==1
    assert connections[0].commit.call_count==3
    assert connections[0].cursor.return_value.close.call_count>=3


def test_failed_transaction_rolls_back_before_connection_is_reused(database):
    repository,connections=database
    with pytest.raises(HTTPException):
        with repository.transaction():raise RuntimeError('synthetic-query-failure')
    with repository.transaction() as cur:cur.execute('SELECT 1')
    assert len(connections)==1
    assert connections[0].rollback.called


def test_pool_exhaustion_is_bounded_and_does_not_open_extra_connections(database):
    repository,connections=database
    release=threading.Event();entered=threading.Barrier(3)
    def hold():
        with repository.transaction():
            entered.wait(timeout=2);release.wait(timeout=2)
    with ThreadPoolExecutor(max_workers=3) as workers:
        first=workers.submit(hold);second=workers.submit(hold)
        try:
            entered.wait(timeout=2)
            def third():
                with repository.transaction():pass
            with pytest.raises(HTTPException) as error:workers.submit(third).result(timeout=1)
            assert error.value.status_code==503
            assert len(connections)==2
        finally:release.set()
        first.result();second.result()


def test_context_manager_releases_lease_and_closed_lease_cannot_be_reused(database):
    from app.data.postgres import connect
    import psycopg2
    with connect('postgresql://synthetic-pool-test') as first:
        first.cursor().execute('SELECT 1')
    with connect('postgresql://synthetic-pool-test') as second:
        assert first.closed
        with pytest.raises(psycopg2.InterfaceError):
            first.cursor()
        second.cursor().execute('SELECT 2')
    assert len(database[1]) == 1


def test_different_database_urls_never_share_connections(database):
    from app.data.postgres import connect
    with connect('postgresql://synthetic-service'):
        pass
    with connect('postgresql://synthetic-memory'):
        pass
    assert len(database[1]) == 2


def test_connection_failure_diagnostics_do_not_include_credentials(database, monkeypatch):
    from app.data.postgres import connect, DatabaseUnavailableError
    secret_dsn = 'postgresql://synthetic:private-password@invalid/test'
    def fail(*args, **kwargs):
        raise RuntimeError(secret_dsn)
    monkeypatch.setattr('psycopg2.connect', fail)
    with pytest.raises(DatabaseUnavailableError) as error:
        connect(secret_dsn)
    assert 'private-password' not in str(error.value)
    assert error.value.__suppress_context__
