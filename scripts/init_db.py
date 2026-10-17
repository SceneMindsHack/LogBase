"""Create a separate database, preserving any existing sample tables in postgres."""
from docker_db import execute

if __name__ == '__main__':
    result = execute("SELECT datname FROM pg_database WHERE datname = 'logbase'", 'postgres')
    if 'logbase' in result.splitlines()[1:]:
        print('Database logbase already exists; preserved')
    else:
        print(execute('CREATE DATABASE logbase', 'postgres'))
