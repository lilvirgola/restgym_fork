import common

import os
import sys
import sqlite3
import json
import re
import time as time_module
import concurrent.futures
import multiprocessing
import math
import datetime
import csv
import ast
from rich.progress import Progress
from rich import print

MULTITHREADING = True
MAX_WORKERS = 8
DEFAULT_JACCARD_SIMILARITY_THRESHOLD = 0.7
JACCARD_SIMILARITY_THRESHOLDS = {
    'features-service': 0.8,
    'languagetool': 0.8,
    'person-controller': 0.9,
    'scs': 0.7,
    'genome-nexus': 0.7,
    'market': 0.7,
    'project-tracking-system': 0.9,
    'user-management': 0.7,
    'ncs': 0.7,
    'restcountries': 0.7,
    'newbee': 0.7,
    'blog': 0.7,
    'google-drive': 0.7,
    'erc20': 0.8,
    'flight-search': 0.7,
    'gestao-hospital': 0.7,
    'kafka-rest-proxy': 0.7,
    'notebook-manager': 0.7,
    'pet-clinic': 0.7,
}
JACCARD_SIMILARITY_THRESHOLD_FALLBACK = 0.7

def collect_completed_runs():
    completed_runs = set()
    api_dirs = os.scandir(
        f'{common.RESTGYM_BASE_DIR}/results'
    )
    for api_dir in api_dirs:
        if api_dir.is_dir():
            tool_dirs = os.scandir(api_dir.path)
            for tool_dir in tool_dirs:
                if tool_dir.is_dir():
                    run_dirs = os.scandir(tool_dir.path)
                    for run_dir in run_dirs:
                        if os.path.exists(
                            run_dir.path + '/completed.txt'
                        ):
                            completed_runs.add(run_dir.path)
    return completed_runs

def collect_verified_runs():
    verified_runs = set()
    api_dirs = os.scandir(
        f'{common.RESTGYM_BASE_DIR}/results'
    )
    for api_dir in api_dirs:
        if api_dir.is_dir():
            tool_dirs = os.scandir(api_dir.path)
            for tool_dir in tool_dirs:
                if tool_dir.is_dir():
                    run_dirs = os.scandir(tool_dir.path)
                    for run_dir in run_dirs:
                        if os.path.exists(
                            run_dir.path + '/verified.txt'
                        ):
                            verified_runs.add(run_dir.path)
    return verified_runs

def collect_processed_runs():
    processed_runs = set()
    api_dirs = os.scandir(
        f'{common.RESTGYM_BASE_DIR}/results'
    )
    for api_dir in api_dirs:
        if api_dir.is_dir():
            tool_dirs = os.scandir(api_dir.path)
            for tool_dir in tool_dirs:
                if tool_dir.is_dir():
                    run_dirs = os.scandir(tool_dir.path)
                    for run_dir in run_dirs:
                        if os.path.exists(
                            run_dir.path + '/summary.json'
                        ):
                            processed_runs.add(run_dir.path)
    return processed_runs

def collect_summaries():
    summaries = set()
    api_dirs = os.scandir(
        f'{common.RESTGYM_BASE_DIR}/results'
    )
    for api_dir in api_dirs:
        if api_dir.is_dir():
            tool_dirs = os.scandir(api_dir.path)
            for tool_dir in tool_dirs:
                if tool_dir.is_dir():
                    run_dirs = os.scandir(tool_dir.path)
                    for run_dir in run_dirs:
                        if os.path.exists(
                            run_dir.path + '/summary.json'
                        ):
                            summaries.add(
                                run_dir.path + '/summary.json'
                            )
    return summaries

def parse_started_timestamp(path):
    started_path = os.path.join(path, 'started.txt')
    if not os.path.exists(started_path):
        return None
    try:
        with open(started_path, 'r') as f:
            content = f.read()
        match = re.search(r'Run started on (.+?)\.\s*$', content, re.MULTILINE)
        if not match:
            return None
        time_str = match.group(1).strip()
        struct_time = time_module.strptime(time_str, "%a %b %d %H:%M:%S %Y")
        return time_module.mktime(struct_time)
    except Exception as e:
        print(f" => [yellow]WARN[/yellow] Could not parse started.txt at {started_path}: {e}")
        return None


def parse_time_budget(**file_path):
    with open(mode='r', **file_path) as f:
        content = f.read()
        
    match = re.search(
        r'Time budget:\s*(\d+)',
        content
    )
    if match:
        minutes = int(match.group(1))

        if minutes > 0:
            return minutes

    return 60

def extract_minimum_req_num():
    result = {}
    processed_runs = collect_processed_runs()
    for processed_run in processed_runs:
        api = processed_run.split('/')[-3]

        with open(
            f"{processed_run}/summary.json",
            'r'
        ) as summary_file:
            req_num = json.load(
                summary_file
            )['interactions']['count']

            if api not in result or result[api] > req_num:
                result[api] = req_num
    return result

def compute_stats_on_interactions(
    conn: sqlite3.Connection,
    mutant_id
):
    cursor = conn.cursor()

    interactions_stats = {}

    interactions_stats['count'] = cursor.execute(
        'SELECT COUNT(1) FROM interactions'
    ).fetchone()[0]

    interactions_stats['2XX'] = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM interactions
        WHERE response_status_code >= 200
          AND response_status_code < 300
        '''
    ).fetchone()[0]

    interactions_stats['4XX'] = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM interactions
        WHERE response_status_code >= 400
          AND response_status_code < 500
        '''
    ).fetchone()[0]

    interactions_stats['5XX'] = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM interactions
        WHERE response_status_code >= 500
          AND response_status_code < 600
        '''
    ).fetchone()[0]

    interactions_stats['401'] = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM interactions
        WHERE response_status_code = 401
        '''
    ).fetchone()[0]

    interactions_stats['403'] = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM interactions
        WHERE response_status_code = 403
        '''
    ).fetchone()[0]

    interactions_stats['covered_operations'] = cursor.execute(
        'SELECT COUNT(DISTINCT operation_id) FROM interactions'
    ).fetchone()[0]

    interactions_stats['unique_5XX'] = cursor.execute(
        'SELECT COUNT(DISTINCT error_bucket_id) FROM interactions'
    ).fetchone()[0]

    # Mutation execution statistics.
    if mutant_id:
        execution_count = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM interactions
            WHERE mutant_id = ?
            ''',
            (mutant_id,)
        ).fetchone()[0]

        first_execution_ts_raw = cursor.execute(
            '''
            SELECT MIN(request_timestamp)
            FROM interactions
            WHERE mutant_id = ?
            ''',
            (mutant_id,)
        ).fetchone()[0]

        try:
            first_execution_ts = (
                float(first_execution_ts_raw)
                if first_execution_ts_raw is not None
                else None
            )
        except (ValueError, TypeError):
            first_execution_ts = None

        first_execution_interaction = cursor.execute(
            '''
            SELECT MIN(id)
            FROM interactions
            WHERE mutant_id = ?
            ''',
            (mutant_id,)
        ).fetchone()[0]

        interactions_stats['execution_count'] = execution_count
        interactions_stats['first_execution_timestamp'] = (
            first_execution_ts
        )
        interactions_stats[
            'interactions_to_first_execution'
        ] = first_execution_interaction

    else:
        interactions_stats['execution_count'] = 0
        interactions_stats['first_execution_timestamp'] = None
        interactions_stats[
            'interactions_to_first_execution'
        ] = None

    return interactions_stats

def prepare_database(
    conn: sqlite3.Connection,
    count,
    total
):
    cursor = conn.cursor()

    interactions_table = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'interactions'
        '''
    ).fetchone()[0]

    if interactions_table == 0:
        print(
            f" => [red]ERROR[/red] "
            f"({count}/{total}) "
            f"Missing interaction table."
        )
        return False

    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS
        idx_interaction_response_status_code
        ON interactions (response_status_code ASC)
        '''
    )

    mutant_id_exists = cursor.execute(
        '''
        SELECT COUNT(1)
        FROM pragma_table_info('interactions')
        WHERE name = 'mutant_id'
        '''
    ).fetchone()[0]

    if mutant_id_exists == 0:
        cursor.execute(
            '''
            ALTER TABLE interactions
            ADD COLUMN mutant_id TEXT
            '''
        )

    columns = [
        'operation_id',
        'error_bucket_id'
    ]

    for column in columns:
        column_count = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM pragma_table_info('interactions')
            WHERE name = ?
            ''',
            (column,)
        ).fetchone()[0]

        if column_count < 1:
            cursor.execute(
                f'''
                ALTER TABLE interactions
                ADD COLUMN {column} INTEGER
                '''
            )
        else:
            cursor.execute(
                f'''
                UPDATE interactions
                SET {column} = NULL
                '''
            )

    mutation_columns = [
        'mutant_id TEXT',
        'mutant_operator TEXT',
        'mutant_taxonomy TEXT',
        'is_reached INTEGER'
    ]

    for col_def in mutation_columns:
        col_name = col_def.split()[0]

        column_count = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM pragma_table_info('interactions')
            WHERE name = ?
            ''',
            (col_name,)
        ).fetchone()[0]

        if column_count < 1:
            cursor.execute(
                f'''
                ALTER TABLE interactions
                ADD COLUMN {col_def}
                '''
            )

    cursor.execute(
        '''
        CREATE INDEX IF NOT EXISTS
        idx_interaction_mutant_id
        ON interactions (mutant_id)
        '''
    )

    cursor.execute(
        'UPDATE interactions SET is_reached = NULL'
    )

    cursor.execute(
        'DROP TABLE IF EXISTS code_coverage'
    )

    cursor.execute(
        '''
        CREATE TABLE code_coverage (
            id INTEGER PRIMARY KEY,
            sample_time TEXT,
            branch_coverage FLOAT,
            line_coverage FLOAT,
            method_coverage FLOAT
        )
        '''
    )

    cursor.execute(
        'DROP TABLE IF EXISTS cumulative_results'
    )

    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS cumulative_results (
            id INTEGER PRIMARY KEY,
            interaction_number INTEGER,
            request_time REAL,
            success_count INTEGER,
            client_error_count INTEGER,
            server_error_count INTEGER,
            operation_coverage INTEGER,
            unique_faults INTEGER,
            branch_coverage REAL,
            line_coverage REAL,
            method_coverage REAL
        )
        '''
    )

    conn.commit()

    return True

def get_operations(api):
    spec_path = (
        f'{common.RESTGYM_BASE_DIR}/apis/'
        f'{api}/specifications/'
        f'{api}-openapi.json'
    )

    operations = []

    operation_id = 0

    methods = [
        'CONNECT',
        'DELETE',
        'GET',
        'HEAD',
        'OPTIONS',
        'PATCH',
        'POST',
        'PUT',
        'TRACE'
    ]

    with open(spec_path, 'r') as spec_file:
        paths = json.load(spec_file)['paths']

        for path in paths.keys():
            for method in methods:
                if method.lower() in paths[path]:
                    operations.append({
                        'id': operation_id,
                        'method': method,
                        'path': path
                    })

                    operation_id += 1

    return operations

def extract_operation_id_from_interaction(
    path,
    conn: sqlite3.Connection,
    count,
    total
):
    api = path.split('/')[-3]

    cursor = conn.cursor()

    operations = get_operations(api)

    for operation in operations:
        regex = operation['path']

        while regex.find('{') > 0:
            start = regex.find('{')
            end = regex.find('}') + 1

            regex = regex.replace(
                regex[start:end],
                '[^/]*'
            )

        regex = regex.replace(
            '/',
            r'/'
        )

        if not regex.endswith('/'):
            regex += r'/'

        regex += '?'

        operation['regex'] = regex

    interactions = cursor.execute(
        '''
        SELECT id, request_method, request_path
        FROM interactions
        WHERE response_status_code >= 200
          AND response_status_code < 300
        '''
    ).fetchall()

    already_alerted = False

    for interaction in interactions:
        interaction_id = interaction[0]

        interaction_method = interaction[1]

        if interaction_method == 'HEAD':
            interaction_method = 'GET'

        interaction_path = (
            interaction[2]
            .split('?')[0]
            .replace('//', '/')
        )

        found_match = False

        for operation in operations:
            if interaction_method == operation['method']:
                match = re.search(
                    operation['regex'],
                    interaction_path
                )

                if (
                    match is not None
                    and (
                        match.span()[1]
                        == len(interaction_path)
                        or (
                            match.span()[1]
                            < len(interaction_path)
                            and interaction_path[
                                match.span()[1]
                            ] == '?'
                        )
                    )
                ):
                    found_match = True

                    cursor.execute(
                        '''
                        UPDATE interactions
                        SET operation_id = ?
                        WHERE id = ?
                        ''',
                        (
                            operation['id'],
                            interaction_id
                        )
                    )

                    break

        if (
            not found_match
            and api != 'languagetool'
            and not already_alerted
        ):
            print(
                f" => [yellow]-WARN[/yellow] "
                f"({count}/{total}) "
                f"NO_PATH_MATCH: "
                f"{interaction_method} "
                f"{interaction_path}."
            )

            already_alerted = True

    conn.commit()


def jaccard_similarity(list1, list2):
    set1 = set(list1)
    set2 = set(list2)

    intersection = len(
        set1.intersection(set2)
    )

    union = len(set1) + len(set2) - intersection

    if union == 0:
        return 1.0

    return float(intersection) / union


def preprocess_response_body(api, response_body):
    if api in ['languagetool']:
        response_body = (
            response_body
            .split('\n')[0]
            .removeprefix(
                "Error: Internal Error: "
            )
            .replace(
                "(''' (code 39))",
                "( (code 39))"
            )
        )

        response_body = re.sub(
            "'[^']*'",
            ' ',
            re.sub(
                '"[^"]*"',
                ' ',
                re.sub(
                    '[^a-zA-Z]+',
                    ' ',
                    response_body
                )
            )
        )

    elif api in ['features-service']:
        if (
            '<body>' in response_body
            and '</body>' in response_body
        ):
            response_body = response_body[
                response_body.find('<body>'):
                response_body.find('</body>')
            ]

    elif api in [
        'market',
        'user-management',
        'blog',
        'erc20',
        'gestao-hospital'
    ]:
        try:
            message = (
                json.loads(response_body)
            )['message']

            if (
                api in [
                    'market',
                    'erc20',
                    'gestao-hospital'
                ]
                or len(message.strip()) > 4
            ):
                response_body = message

        except Exception:
            pass

        if api == 'market':
            response_body = re.sub(
                r'\[.*\]',
                '',
                response_body
            )

    elif api in ['person-controller']:
        response_body = (
            response_body
            .replace('"', ' ')
            .replace(':', ' ')
            .replace('{', ' ')
            .replace('}', ' ')
            .replace('[', ' ')
            .replace(']', ' ')
            .replace(',', ' ')
        )

    elif api in ['pet-clinic']:
        try:
            json_content = json.loads(
                response_body
            )

            message = (
                json_content['title']
                + ' '
                + json_content['detail']
            )

            if len(message.strip()) > 4:
                response_body = message

        except Exception:
            pass

    return response_body


def bucket_unique_5xx(
    path,
    conn: sqlite3.Connection,
    count,
    total
):
    api = path.split('/')[-3]

    cursor = conn.cursor()

    interactions = cursor.execute(
        '''
        SELECT id, response_content
        FROM interactions
        WHERE response_status_code >= 500
        '''
    ).fetchall()

    bucket_count = 0
    buckets = []

    for interaction in interactions:
        interaction_id = interaction[0]

        words = preprocess_response_body(
            api,
            interaction[1]
        ).split()

        if len(words) == 0:
            words = ['500']

        candidate_bucket = None
        candidate_similarity = 0

        for bucket in buckets:
            similarity = jaccard_similarity(
                words,
                bucket['words']
            )

            threshold = (
                JACCARD_SIMILARITY_THRESHOLDS.get(
                    api,
                    JACCARD_SIMILARITY_THRESHOLD_FALLBACK
                )
            )

            if (
                similarity >= threshold
                and similarity > candidate_similarity
            ):
                candidate_similarity = similarity
                candidate_bucket = bucket

        if candidate_bucket is None:
            candidate_bucket = {
                'words': words,
                'id': bucket_count
            }

            bucket_count += 1
            buckets.append(candidate_bucket)

        cursor.execute(
            '''
            UPDATE interactions
            SET error_bucket_id = ?
            WHERE id = ?
            ''',
            (
                candidate_bucket['id'],
                interaction_id
            )
        )

    conn.commit()


def compute_code_coverage_on_sample(path_to_csv):
    code_coverage = {}

    (
        total_branch,
        covered_branch,
        total_line,
        covered_line,
        total_method,
        covered_method
    ) = (0, 0, 0, 0, 0, 0)

    with open(path_to_csv) as f:
        for line in f.readlines():
            items = line.split(',')

            if (
                '_COVERED' not in items[6]
                and '_MISSED' not in items[6]
            ):
                covered_branch += int(items[6])

                total_branch += (
                    int(items[6])
                    + int(items[5])
                )

                covered_line += int(items[8])

                total_line += (
                    int(items[8])
                    + int(items[7])
                )

                covered_method += int(items[12])

                total_method += (
                    int(items[12])
                    + int(items[11])
                )

    code_coverage['branch'] = (
        covered_branch / total_branch
        if total_branch > 0
        else 0
    )

    code_coverage['line'] = (
        covered_line / total_line
        if total_line > 0
        else 0
    )

    code_coverage['method'] = (
        covered_method / total_method
        if total_method > 0
        else 0
    )

    return code_coverage


def extract_code_coverage(
    path,
    conn: sqlite3.Connection
):
    cursor = conn.cursor()

    cov_dir = path + common.CODE_COVERAGE_PATH

    if not os.path.exists(cov_dir):
        return

    for file in os.listdir(cov_dir):
        if file.endswith('.csv'):
            code_coverage = (
                compute_code_coverage_on_sample(
                    f'{cov_dir}/{file}'
                )
            )

            time_str = (
                file
                .removeprefix('jacoco_')
                .removesuffix('.csv')
                .replace('.', ':')
            )

            cursor.execute(
                '''
                INSERT INTO code_coverage (
                    sample_time,
                    branch_coverage,
                    line_coverage,
                    method_coverage
                )
                VALUES (?, ?, ?, ?)
                ''',
                (
                    time_str,
                    code_coverage['branch'],
                    code_coverage['line'],
                    code_coverage['method']
                )
            )

    conn.commit()


def get_final_coverage(conn: sqlite3.Connection):
    cursor = conn.cursor()

    code_coverage = cursor.execute(
        '''
        SELECT
            branch_coverage,
            line_coverage,
            method_coverage
        FROM code_coverage
        ORDER BY sample_time DESC
        LIMIT 1
        '''
    ).fetchone()

    if code_coverage is None:
        return {
            'branch': 0.0,
            'line': 0.0,
            'method': 0.0
        }

    return {
        'branch': code_coverage[0],
        'line': code_coverage[1],
        'method': code_coverage[2]
    }


def compute_cumulative_results(
    conn: sqlite3.Connection
):
    MAX_SAMPLE_STEP = 100

    cursor = conn.cursor()

    upper_limit = cursor.execute(
        'SELECT COUNT(1) FROM interactions'
    ).fetchone()[0]

    if upper_limit == 0:
        return

    SAMPLE_STEP = min(
        MAX_SAMPLE_STEP,
        upper_limit
    )

    i = SAMPLE_STEP

    while i <= upper_limit:
        successes = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM interactions
            WHERE response_status_code >= 200
              AND response_status_code < 300
              AND id <= ?
            ''',
            (i,)
        ).fetchone()[0]

        client_failures = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM interactions
            WHERE response_status_code >= 400
              AND response_status_code < 500
              AND id <= ?
            ''',
            (i,)
        ).fetchone()[0]

        server_failures = cursor.execute(
            '''
            SELECT COUNT(1)
            FROM interactions
            WHERE response_status_code >= 500
              AND response_status_code < 600
              AND id <= ?
            ''',
            (i,)
        ).fetchone()[0]

        operations_coverage = cursor.execute(
            '''
            SELECT COUNT(DISTINCT operation_id)
            FROM interactions
            WHERE operation_id IS NOT NULL
              AND id <= ?
            ''',
            (i,)
        ).fetchone()[0]

        unique_faults = cursor.execute(
            '''
            SELECT COUNT(DISTINCT error_bucket_id)
            FROM interactions
            WHERE error_bucket_id IS NOT NULL
              AND id <= ?
            ''',
            (i,)
        ).fetchone()[0]

        timestamps = cursor.execute(
            '''
            SELECT request_timestamp, response_timestamp
            FROM interactions
            WHERE id = ?
            ''',
            (i,)
        ).fetchone()

        if (
            timestamps is None
            or timestamps[0] is None
            or timestamps[1] is None
        ):
            i += SAMPLE_STEP
            continue

        try:
            req_ts = float(timestamps[0])
            res_ts = float(timestamps[1])
        except (ValueError, TypeError):
            i += SAMPLE_STEP
            continue

        average_timestamp = round(
            (req_ts + res_ts) / 2
        )

        string_time = (
            datetime.datetime.fromtimestamp(
                average_timestamp,
                datetime.timezone.utc
            ).isoformat()
        )

        row = cursor.execute(
            '''
            SELECT
                branch_coverage,
                line_coverage,
                method_coverage,
                ABS(
                    strftime("%s", sample_time)
                    - strftime("%s", ?)
                ) AS time_distance
            FROM code_coverage
            ORDER BY time_distance
            LIMIT 1
            ''',
            (string_time,)
        ).fetchone()

        if row is None:
            i += SAMPLE_STEP
            continue

        if row[3] > 5:
            print(
                " => [yellow]-WARN[/yellow] "
                "Code coverage sample too far "
                "away in time."
            )

        cursor.execute(
            '''
            INSERT INTO cumulative_results (
                interaction_number,
                request_time,
                success_count,
                client_error_count,
                server_error_count,
                operation_coverage,
                unique_faults,
                branch_coverage,
                line_coverage,
                method_coverage
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                i,
                req_ts,
                successes,
                client_failures,
                server_failures,
                operations_coverage,
                unique_faults,
                row[0],
                row[1],
                row[2]
            )
        )

        i += SAMPLE_STEP

    conn.commit()


def load_campaign_data(path):
    campaign_path = os.path.join(
        path,
        'campaign.json'
    )

    if os.path.exists(campaign_path):
        with open(campaign_path, 'r') as f:
            return json.load(f)

    return None


def evaluate_mutation_execution(
    path,
    campaign_data,
    interactions_stats,
    conn
):
    """
    Computes mutation execution metrics for the active mutant.
    The proxy execution log is used as a fallback source when
    SQLite does not contain mutant_id information.
    """
    if (
        not campaign_data
        or campaign_data.get('mode') == 'baseline'
    ):
        return {
            'is_reached': False,
            'time_to_first_execution': None,
            'interactions_to_first_execution': None,
            'execution_count': 0,
            'reason': 'baseline_or_no_campaign'
        }

    mutant = campaign_data.get('mutant', {})
    mutant_id = mutant.get('id', 'unknown')

    execution_count = interactions_stats.get(
        'execution_count',
        0
    )

    first_execution_ts = interactions_stats.get(
        'first_execution_timestamp'
    )

    first_execution_interaction = interactions_stats.get(
        'interactions_to_first_execution'
    )

    # If SQLite didn't capture the mutant_id due to addon
    # execution order, fall back to proxy.exec.jsonl.
    if execution_count == 0:
        proxy_log_path = os.path.join(
            path,
            'proxy.exec.jsonl'
        )

        if os.path.exists(proxy_log_path):
            proxy_executions = []

            try:
                with open(proxy_log_path, 'r') as f:
                    for line in f:
                        line = line.strip()

                        if not line:
                            continue

                        entry = None

                        # Try standard JSON first.
                        try:
                            entry = json.loads(line)

                        except json.JSONDecodeError:
                            # Fallback for Python str(dict)
                            # format with single quotes.
                            try:
                                entry = ast.literal_eval(line)

                            except Exception:
                                continue

                        if not isinstance(entry, dict):
                            continue

                        logged_id = str(
                            entry.get('mutant_id', '')
                        )

                        status = str(
                            entry.get('status', '')
                        )

                        if (
                            status == 'EXECUTED'
                            and logged_id == mutant_id
                        ):
                            ts_val = entry.get(
                                'timestamp'
                            )

                            if ts_val is not None:
                                try:
                                    # Handle ISO 8601 timestamps.
                                    if isinstance(
                                        ts_val,
                                        str
                                    ):
                                        dt = (
                                            datetime.datetime
                                            .fromisoformat(
                                                ts_val.replace(
                                                    'Z',
                                                    '+00:00'
                                                )
                                            )
                                        )

                                        ts = dt.timestamp()

                                    else:
                                        ts = float(ts_val)

                                    proxy_executions.append(ts)

                                except (
                                    ValueError,
                                    TypeError
                                ):
                                    proxy_executions.append(
                                        None
                                    )

                            else:
                                proxy_executions.append(
                                    None
                                )

                if proxy_executions:
                    execution_count = len(
                        proxy_executions
                    )

                    valid_timestamps = [
                        t
                        for t in proxy_executions
                        if t is not None
                    ]

                    first_proxy_ts = (
                        min(valid_timestamps)
                        if valid_timestamps
                        else None
                    )

                    # Cross-reference with SQLite to get the
                    # corresponding interaction index/time.
                    if (
                        first_proxy_ts is not None
                        and conn is not None
                    ):
                        try:
                            cursor = conn.cursor()

                            row = cursor.execute(
                                '''
                                SELECT
                                    id,
                                    request_timestamp
                                FROM interactions
                                WHERE request_timestamp IS NOT NULL
                                ORDER BY ABS(
                                    CAST(request_timestamp AS REAL)
                                    - ?
                                )
                                LIMIT 1
                                ''',
                                (first_proxy_ts,)
                            ).fetchone()

                            if row:
                                first_execution_interaction = (
                                    row[0]
                                )

                                try:
                                    first_execution_ts = float(
                                        row[1]
                                    )

                                except (
                                    ValueError,
                                    TypeError
                                ):
                                    first_execution_ts = (
                                        first_proxy_ts
                                    )

                            else:
                                first_execution_ts = (
                                    first_proxy_ts
                                )

                        except Exception as e:
                            print(
                                f" => [yellow]WARN[/yellow] "
                                f"Could not cross-reference "
                                f"proxy log with SQLite: {e}"
                            )

                            first_execution_ts = (
                                first_proxy_ts
                            )

                    else:
                        first_execution_ts = (
                            first_proxy_ts
                        )

            except Exception as e:
                print(
                    f" => [yellow]WARN[/yellow] "
                    f"Could not parse proxy log at "
                    f"{proxy_log_path}: {e}"
                )

    is_reached = execution_count > 0

    time_to_first_execution = None

    if (
        is_reached
        and first_execution_ts is not None
    ):
        start_ts = parse_started_timestamp(path)

        if start_ts is not None:
            time_to_first_execution = round(
                first_execution_ts - start_ts,
                3
            )

            if time_to_first_execution < 0:
                time_to_first_execution = 0.0

    reason = (
        'is_reached'
        if is_reached
        else 'not_reached_within_budget'
    )

    return {
        'is_reached': is_reached,
        'time_to_first_execution': time_to_first_execution,
        'interactions_to_first_execution':
            first_execution_interaction,
        'execution_count': execution_count,
        'reason': reason
    }


def apply_reachability_to_database(
    conn: sqlite3.Connection,
    mutant_id,
    is_reached
):
    """
    Tag every interaction associated with this mutant as
    reached (1) or not reached (0).
    """
    if not mutant_id:
        return

    cursor = conn.cursor()

    reached_value = 1 if is_reached else 0

    cursor.execute(
        '''
        UPDATE interactions
        SET is_reached = ?
        WHERE mutant_id = ?
        ''',
        (
            reached_value,
            mutant_id
        )
    )

    conn.commit()


def compute_mutation_coverage(
    path,
    interactions_stats
):
    api = path.split('/')[-3]

    manifest_path = (
        f"{common.RESTGYM_BASE_DIR}/apis/"
        f"{api}/campaigns/manifest.jsonl"
    )

    total_generated = 0

    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        if (
                            json.loads(line).get(
                                'mode'
                            ) != 'baseline'
                        ):
                            total_generated += 1

                    except Exception:
                        pass

    reached_count = (
        1
        if interactions_stats.get(
            'execution_count',
            0
        ) > 0
        else 0
    )

    interactions_stats[
        'mutation_total_generated'
    ] = total_generated

    interactions_stats[
        'mutation_reached'
    ] = reached_count


def process_runs(paths):
    if not paths:
        return

    threads = min(
        MAX_WORKERS,
        max(
            1,
            multiprocessing.cpu_count()
        )
    )

    total = len(paths)

    with Progress() as progress:
        # process_run performs 10 progress updates.
        analysis_task = progress.add_task(
            "Analyzing...",
            total=total * 10
        )

        if MULTITHREADING:
            futures = []

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=threads
            ) as executor:

                for count, path in enumerate(
                    paths,
                    start=1
                ):
                    future = executor.submit(
                        process_run,
                        path,
                        count,
                        total,
                        progress,
                        analysis_task
                    )

                    futures.append(
                        (future, path, count)
                    )

                # Calling result() propagates worker exceptions.
                for future, path, count in futures:
                    try:
                        future.result()

                    except Exception as e:
                        print(
                            f"\n[red]WORKER FAILED[/red] "
                            f"({count}/{total}) "
                            f"{path}"
                        )

                        print(
                            f"[red]"
                            f"{type(e).__name__}: {e}"
                            f"[/red]"
                        )

                        raise

        else:
            for count, path in enumerate(
                paths,
                start=1
            ):
                process_run(
                    path,
                    count,
                    total,
                    progress,
                    analysis_task
                )

    results_time = datetime.datetime.now().strftime(
        '%Y%m%d-%H%M%S'
    )

    header = [
        'api',
        'tool',
        'run',
        'campaign_id',
        'mutant_id',
        'mutant_operator',
        'mutant_taxonomy',
        'is_reached',
        'time_to_first_execution_sec',
        'interactions_to_first_execution',
        'execution_count',
        'execution_reason',
        'interactions',
        '2XX',
        '4XX',
        '5XX',
        'covered_operations',
        'unique_5XX',
        'mut_total_generated',
        'branch_cov',
        'line_cov',
        'method_cov',
        'area_2XX',
        'area_4XX',
        'area_5XX',
        'area_ops',
        'area_faults',
        'area_branch',
        'area_line',
        'area_method'
    ]

    summaries = collect_summaries()

    time_budget_output = (
        f"{common.RESTGYM_BASE_DIR}/results/"
        f"time_budget_aggregated_results_"
        f"{results_time}.csv"
    )

    with open(
        time_budget_output,
        mode='w',
        newline=''
    ) as aggregate_file:
        writer = csv.writer(
            aggregate_file,
            delimiter=',',
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL
        )

        writer.writerow(header)

        for summary in summaries:
            api_info = summary.split('/')

            db_path = str(summary).replace(
                "summary.json",
                common.DB_FILENAME
            )

            conn = sqlite3.connect(db_path)

            try:
                aucs = conn.cursor().execute(
                    """
                    WITH pairs AS (
                        SELECT
                            LAG(request_time)
                                OVER (
                                    ORDER BY request_time
                                ) AS t1,

                            request_time AS t2,

                            success_count,

                            LAG(success_count)
                                OVER (
                                    ORDER BY request_time
                                ) AS success1,

                            client_error_count,

                            LAG(client_error_count)
                                OVER (
                                    ORDER BY request_time
                                ) AS client1,

                            server_error_count,

                            LAG(server_error_count)
                                OVER (
                                    ORDER BY request_time
                                ) AS server1,

                            operation_coverage,

                            LAG(operation_coverage)
                                OVER (
                                    ORDER BY request_time
                                ) AS coverage1,

                            unique_faults,

                            LAG(unique_faults)
                                OVER (
                                    ORDER BY request_time
                                ) AS faults1,

                            branch_coverage,

                            LAG(branch_coverage)
                                OVER (
                                    ORDER BY request_time
                                ) AS branch1,

                            line_coverage,

                            LAG(line_coverage)
                                OVER (
                                    ORDER BY request_time
                                ) AS line1,

                            method_coverage,

                            LAG(method_coverage)
                                OVER (
                                    ORDER BY request_time
                                ) AS method1

                        FROM cumulative_results
                    )

                    SELECT
                        SUM(
                            (success1 + success_count)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (client1 + client_error_count)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (server1 + server_error_count)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (coverage1 + operation_coverage)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (faults1 + unique_faults)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (branch1 + branch_coverage)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (line1 + line_coverage)
                            / 2.0
                            * (t2 - t1)
                        ),

                        SUM(
                            (method1 + method_coverage)
                            / 2.0
                            * (t2 - t1)
                        )

                    FROM pairs
                    WHERE t1 IS NOT NULL;
                    """
                ).fetchone()

                if aucs is None:
                    aucs = (0,) * 8

                aucs = tuple(
                    0 if x is None else x
                    for x in aucs
                )

            finally:
                conn.close()

            with open(summary) as f:
                d = json.load(f)

            v = d.get(
                'mutation_execution',
                {}
            )

            i = d.get(
                'interactions',
                {}
            )

            c = d.get(
                'final_code_coverage',
                {}
            )

            writer.writerow([
                api_info[-4],
                api_info[-3],
                api_info[-2],

                v.get('campaign_id', ''),
                v.get('mutant_id', ''),
                v.get('operator', ''),
                v.get('taxonomy', ''),

                v.get('is_reached', False),
                v.get(
                    'time_to_first_execution'
                ),
                v.get(
                    'interactions_to_first_execution'
                ),
                v.get(
                    'execution_count',
                    0
                ),
                v.get(
                    'reason',
                    ''
                ),

                i.get('count', 0),
                i.get('2XX', 0),
                i.get('4XX', 0),
                i.get('5XX', 0),
                i.get('covered_operations', 0),
                i.get('unique_5XX', 0),

                i.get(
                    'mutation_total_generated',
                    0
                ),

                c.get('branch', 0.0),
                c.get('line', 0.0),
                c.get('method', 0.0),

                aucs[0],
                aucs[1],
                aucs[2],
                aucs[3],
                aucs[4],
                aucs[5],
                aucs[6],
                aucs[7]
            ])

    minimums = extract_minimum_req_num()

    request_budget_output = (
        f"{common.RESTGYM_BASE_DIR}/results/"
        f"request_budget_aggregate_results_"
        f"{results_time}.csv"
    )

    with open(
        request_budget_output,
        mode='w',
        newline=''
    ) as aggregate_file:
        writer = csv.writer(
            aggregate_file,
            delimiter=',',
            quotechar='"',
            quoting=csv.QUOTE_MINIMAL
        )

        writer.writerow(header)

        for processed_run in collect_processed_runs():
            api_info = processed_run.split('/')

            api_name = api_info[-3]

            min_req = minimums.get(
                api_name,
                0
            )

            if min_req == 0:
                continue

            conn = sqlite3.connect(
                processed_run
                + '/'
                + common.DB_FILENAME
            )

            try:
                result = conn.cursor().execute(
                    '''
                    SELECT *
                    FROM cumulative_results
                    WHERE interaction_number = ?
                    ''',
                    (min_req,)
                ).fetchone()

                if result is None:
                    result = conn.cursor().execute(
                        '''
                        SELECT *
                        FROM cumulative_results
                        ORDER BY interaction_number DESC
                        LIMIT 1
                        '''
                    ).fetchone()

                if result is None:
                    result = (
                        0, 0, 0, 0, 0, 0,
                        0, 0, 0.0, 0.0, 0.0
                    )

                area = conn.cursor().execute(
                    '''
                    SELECT
                        SUM(success_count),
                        SUM(client_error_count),
                        SUM(server_error_count),
                        SUM(operation_coverage),
                        SUM(unique_faults),
                        SUM(branch_coverage),
                        SUM(line_coverage),
                        SUM(method_coverage)
                    FROM cumulative_results
                    WHERE interaction_number <= ?
                    ''',
                    (min_req,)
                ).fetchone()

            finally:
                conn.close()

            if area:
                area = tuple(
                    0 if x is None else x
                    for x in area
                )

            else:
                area = (
                    0, 0, 0, 0,
                    0, 0, 0, 0
                )

            with open(
                processed_run + '/summary.json'
            ) as f:
                d = json.load(f)

            v = d.get(
                'mutation_execution',
                {}
            )

            i = d.get(
                'interactions',
                {}
            )

            c = d.get(
                'final_code_coverage',
                {}
            )

            writer.writerow([
                api_name,
                api_info[-2],
                api_info[-1],

                v.get('campaign_id', ''),
                v.get('mutant_id', ''),
                v.get('operator', ''),
                v.get('taxonomy', ''),

                v.get('is_reached', False),
                v.get(
                    'time_to_first_execution'
                ),
                v.get(
                    'interactions_to_first_execution'
                ),
                v.get(
                    'execution_count',
                    0
                ),
                v.get(
                    'reason',
                    ''
                ),

                result[1],
                result[3],
                result[4],
                result[5],
                result[6],
                result[7],

                i.get(
                    'mutation_total_generated',
                    0
                ),

                result[8],
                result[9],
                result[10],

                area[0] / min_req
                if area[0]
                else 0,

                area[1] / min_req
                if area[1]
                else 0,

                area[2] / min_req
                if area[2]
                else 0,

                area[3] / min_req
                if area[3]
                else 0,

                area[4] / min_req
                if area[4]
                else 0,

                area[5] / min_req
                if area[5]
                else 0,

                area[6] / min_req
                if area[6]
                else 0,

                area[7] / min_req
                if area[7]
                else 0,
            ])

    print(
        "[green]Aggregated results saved to CSV files.[/green]"
    )


def process_run(
    path,
    count,
    total,
    progress,
    task
):
    run_name = '/'.join(
        os.path.normpath(path).split(os.sep)[-3:]
    )

    print(
        f" => [green]START[/green] "
        f"({count}/{total}) "
        f"Analyzing run: {run_name}",
        flush=True
    )

    conn = None

    try:
        conn = sqlite3.connect(
            f"{path}/{common.DB_FILENAME}"
        )

        # 1
        database_ready = prepare_database(
            conn,
            count,
            total
        )

        progress.update(
            task,
            advance=1
        )

        if not database_ready:
            raise RuntimeError(
                "Database preparation failed."
            )

        # 2
        extract_operation_id_from_interaction(
            path,
            conn,
            count,
            total
        )

        progress.update(
            task,
            advance=1
        )

        # 3
        bucket_unique_5xx(
            path,
            conn,
            count,
            total
        )

        progress.update(
            task,
            advance=1
        )

        campaign_data = load_campaign_data(path)

        mutant_id = None

        if (
            campaign_data
            and campaign_data.get('mode')
            != 'baseline'
        ):
            mutant_id = (
                campaign_data
                .get('mutant', {})
                .get('id')
            )

        # 4
        interactions_stats = (
            compute_stats_on_interactions(
                conn,
                mutant_id
            )
        )

        progress.update(
            task,
            advance=1
        )

        # 5
        mutation_execution = evaluate_mutation_execution(
            path,
            campaign_data,
            interactions_stats,
            conn
        )

        apply_reachability_to_database(
            conn,
            mutant_id,
            mutation_execution.get(
                'is_reached',
                False
            )
        )

        progress.update(
            task,
            advance=1
        )

        # 6
        extract_code_coverage(
            path,
            conn
        )

        progress.update(
            task,
            advance=1
        )

        # 7
        compute_mutation_coverage(
            path,
            interactions_stats
        )

        progress.update(
            task,
            advance=1
        )

        # 8
        final_code_coverage = get_final_coverage(
            conn
        )

        progress.update(
            task,
            advance=1
        )

        # 9
        compute_cumulative_results(
            conn
        )

        progress.update(
            task,
            advance=1
        )

        summary = {
            'interactions': interactions_stats,

            'final_code_coverage':
                final_code_coverage,

            'mutation_execution': {
                'campaign_id': (
                    campaign_data.get(
                        'campaign_id',
                        'baseline'
                    )
                    if campaign_data
                    else None
                ),

                'mutant_id': mutant_id,

                'operator': (
                    campaign_data
                    .get('mutant', {})
                    .get('operator')
                    if campaign_data
                    else None
                ),

                'taxonomy': (
                    campaign_data
                    .get('mutant', {})
                    .get('taxonomy')
                    if campaign_data
                    else None
                ),

                'is_reached':
                    mutation_execution.get(
                        'is_reached'
                    ),

                'time_to_first_execution':
                    mutation_execution.get(
                        'time_to_first_execution'
                    ),

                'interactions_to_first_execution':
                    mutation_execution.get(
                        'interactions_to_first_execution'
                    ),

                'execution_count':
                    mutation_execution.get(
                        'execution_count'
                    ),

                'reason':
                    mutation_execution.get(
                        'reason'
                    ),
            }
        }

        with open(
            path + '/summary.json',
            'w',
            encoding='utf-8'
        ) as f:
            json.dump(
                summary,
                f,
                ensure_ascii=False,
                indent=4
            )

        print(
            f" => [green]-END-[/green] "
            f"({count}/{total}) "
            f"Analysis completed."
        )

        # 10
        progress.update(
            task,
            advance=1
        )

    except Exception as e:
        print(
            f"\n => [red]FAILED[/red] "
            f"({count}/{total}) "
            f"{run_name}",
            flush=True
        )

        print(
            f" => [red]{type(e).__name__}: {e}[/red]",
            flush=True
        )

        # Re-raise so the Future catches it and
        # future.result() propagates it to the main thread.
        raise

    finally:
        if conn is not None:
            conn.close()


if __name__ == '__main__':
    common.welcome()

    print(
        "This is the data analysis module."
    )

    verified_runs = collect_verified_runs()

    completed_but_not_verified_runs = (
        collect_completed_runs()
        .difference(verified_runs)
    )

    processed_runs = collect_processed_runs()

    not_processed_runs = (
        verified_runs
        .difference(processed_runs)
    )

    if (
        len(completed_but_not_verified_runs) > 0
    ):
        print(
            "[yellow]WARNING[/yellow]: "
            "Some runs are completed but not verified."
        )

    print(
        f"Found {len(verified_runs)} verified run, "
        f"{len(processed_runs)} processed "
        f"({len(not_processed_runs)} to analyze)."
    )

    if len(verified_runs) == 0:
        sys.exit(0)

    print(
        f"[1] (Re-)Analyze all "
        f"({len(verified_runs)})\n"
        f"[2] Analyze new "
        f"({len(not_processed_runs)})"
    )

    choice = input("Your choice: ")

    if choice not in ('1', '2'):
        sys.exit(1)

    if choice == '1':
        process_runs(
            list(verified_runs)
        )

    elif choice == '2':
        process_runs(
            list(not_processed_runs)
        )