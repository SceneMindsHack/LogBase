"""Shared connection: Docker-local psql (default), or password-based psycopg."""
import argparse
import csv
import io
import os
import re
import subprocess
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

CONTROL = re.compile(r'[\x00-\x1f]')


def command(database=None):
    return ['docker', 'exec', '-i', os.environ.get('SERENEDB_CONTAINER', 'serenedb'),
            'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1',
            '-p', '7890', '-U', 'postgres', '-d', database or os.getenv('SERENEDB_DBNAME', 'logbase')]


def docker_execute(query, database=None):
    result = subprocess.run(command(database) + ['--csv', '-c', query],
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def records(query):
    return list(csv.DictReader(io.StringIO(execute(query))))


def copy_value(value):
    if value is None:
        return r'\N'
    if isinstance(value, bool):
        return 't' if value else 'f'
    escaped = str(value).replace('\\', '\\\\')
    return CONTROL.sub(lambda match: f'\\{ord(match.group()):03o}', escaped)


def docker_copy_rows(table, columns, rows):
    # table/columns are code-defined identifiers, never user question text.
    import tempfile
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as errors:
        process = subprocess.Popen(command(), stdin=subprocess.PIPE, stdout=errors,
                                   stderr=errors, text=True, encoding='utf-8')
        try:
            process.stdin.write('BEGIN;\nCOPY ' + table + ' (' + ','.join(columns) + ') FROM STDIN;\n')
            for row in rows:
                process.stdin.write('\t'.join(copy_value(row[column]) for column in columns) + '\n')
            process.stdin.write('\\.\nCOMMIT;\n')
            process.stdin.close()
            code = process.wait()
        except BaseException:
            process.kill()
            process.wait()
            errors.seek(0)
            detail = errors.read()
            if detail:
                print(detail)
            raise
        errors.seek(0)
        output = errors.read()
        if code:
            raise RuntimeError(output)
        print(output.strip())


def mode():
    value = os.getenv('SERENEDB_CONNECTION', 'docker')
    if value not in ('docker', 'direct'):
        raise ValueError('SERENEDB_CONNECTION must be docker or direct')
    return value


def connect(database=None):
    password = os.getenv('SERENEDB_PASSWORD')
    if not password:
        raise ValueError('Direct mode needs SERENEDB_PASSWORD; see README connection options')
    return psycopg.connect(host=os.getenv('SERENEDB_HOST', '127.0.0.1'),
        port=int(os.getenv('SERENEDB_PORT', '7890')),
        user=os.getenv('SERENEDB_USER', 'postgres'), password=password,
        dbname=database or os.getenv('SERENEDB_DBNAME', 'logbase'),
        connect_timeout=10, autocommit=True)


def execute(query, database=None):
    if mode() == 'docker':
        return docker_execute(query, database)
    output = io.StringIO()
    writer = csv.writer(output)
    with connect(database) as connection, connection.cursor() as cursor:
        cursor.execute(query, prepare=False)
        while True:
            if cursor.description:
                writer.writerow(column.name for column in cursor.description)
                for row in cursor:
                    writer.writerow('t' if value is True else 'f' if value is False else value for value in row)
            if not cursor.nextset():
                break
    return output.getvalue()


def copy_rows(table, columns, rows):
    if mode() == 'docker':
        return docker_copy_rows(table, columns, rows)
    with connect() as connection:
        with connection.transaction(), connection.cursor() as cursor:
            statement = psycopg.sql.SQL('COPY {} ({}) FROM STDIN').format(
                psycopg.sql.Identifier(table),
                psycopg.sql.SQL(',').join(map(psycopg.sql.Identifier, columns)))
            with cursor.copy(statement) as copy:
                for row in rows:
                    copy.write_row(tuple(row[column] for column in columns))


def literal(value):
    """Quote data values safely for either connection adapter."""
    return psycopg.sql.Literal(value).as_string()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--init', action='store_true', help='Create logbase without altering existing databases')
    action.add_argument('--check', action='store_true')
    action.add_argument('--file', type=Path, help='Execute a trusted repository SQL file')
    args = parser.parse_args()
    if args.init:
        result = execute("SELECT datname FROM pg_database WHERE datname = 'logbase'", 'postgres')
        if 'logbase' in result.splitlines()[1:]:
            print('Database logbase already exists; preserved')
        else:
            print(execute('CREATE DATABASE logbase', 'postgres'))
    elif args.check:
        print(execute('SELECT current_database() AS database, current_user AS username, 1 AS connection_ok'))
    else:
        print(execute(args.file.read_text(encoding='utf-8')))
