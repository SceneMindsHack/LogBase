"""Local Docker/psql connection. Uses container loopback authentication."""
import csv
import io
import os
import re
import subprocess

CONTROL = re.compile(r'[\x00-\x1f]')


def command(database='logbase'):
    return ['docker', 'exec', '-i', os.environ.get('SERENEDB_CONTAINER', 'serenedb'),
            'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1',
            '-p', '7890', '-U', 'postgres', '-d', database]


def execute(query, database='logbase'):
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


def copy_rows(table, columns, rows):
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
