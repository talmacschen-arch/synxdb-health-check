# synxdb-health-check

This tool can be used for health check on SynxDB, CBDB and legacy 2x/3x databases.

## Setup

### Prerequisites
1. A running SynxDB, CBDB or legacy 2x/3x database with `gpadmin` access.
2. `root` access or an OS user with `pip` permission on `master` node.
3. Passwordless `ssh` between master node and segment nodes for `gpadmin` user.

### Download and Install
1. Download `synxdb_health_check.py` and `config.yml` in this repo.
2. Put above 2 files on master node and grant `execute` permission against `synxdb_health_check.py`.

```
chmod +x synxdb_health_check.py
```
3. Install following python library by the user who has `pip` permission.

- If master node has internet access, run following command to install the libary.

```
pip install prettytable
```

- If master node does not have internet access, download the `prettytable.tar.gz` in this repo and upload to master. 

```
tar -xzf prettytable.tar.gz
cd prettytable
pip install prettytable-1.0.1-py2.py3-none-any.whl
```
**Note**: The `whl` files in the above tarball is for CentOS 7.

## Run the health check

1. (Optional) Update the `config.yml` file. 

- **report_format**: `text` or `html`. The `text` format report is printed to the stdout and be saved to `synxdb-health-check-YYYY-MM-DD.rpt` as well. The `html` format report is only saved to `synxdb-health-check-YYYY-MM-DD.html`.
- **rreport_path**: Set the path where the report will be generated to. By default, the report will be created at `/home/gpadmin`.
- **enabled**: Set `true` or `false` to enable or disable a specific check item. By default, all items in the config file will be checked.

2. Run the health check using `gpadmin`.

- On legacy 2x/3x (Python 2):

```
python ./synxdb_health_check.py -f config.yml
```

- In CBDB:

```
python3 ./synxdb_health_check.py -f config.yml
```

## Configurable Parameters

The following parameters in `synxdb_health_check.py` can be configured if needed.

| Parameter  | Description | 
|:------------|:------------|
|MASTER_HOST_NAME|Database master hostname. (Default: localhost)|
|MASTER_PORT|Database master port. (Default: 5432)|
|LONG_RUNNING_QUERY_THRESHOLD|The long running query threshold for the `pg_activity_check`. (Default: 3600s)|
|LOCK_HOLD_TIME|The lock time threshold for the `pg_locks_check`. (Default: 600s)|
|WITHOUT_ANALYZE_DAYS|The days for which tables have not been analyzed. (Default: 7 days)|
|TABLE_MIN_TUPLES_FOR_CHECK|Tables with rowcounts > `TABLE_MIN_TUPLES_FOR_CHECK` will be checked,e.g. bloat check, skew check..etc. (Default: 100000)|
|TABLE_BLOAT_PERCENT|The bloat percent the the `heap_table_bloat_check` and `ao_table_bloat_check`. (Default: 20%)|
|TABLE_UPDATE_COUNT_3X|Get the AO tables list > `TABLE_UPDATE_COUNT_3X` update counts for 3x. (Default: 5000)|
|TABLE_SKEW_PERCENT|Get the table list >  `TABLE_SKEW_PERCENT`% skew. (Default: 20%) |
|TABLE_SKEW_MIN_SIZE_GB|Minimum on-disk size (GB) for a table to be reported by the file-size based skew check (CBDB/2x AO tables). (Default: 1GB) |


## Supported Check Items

| Check Item  | Description | 
|:------------|:------------|
|db_version_check|Check database version |
|seg_config_check| Get `gp_segment_configuration`|
|os_version_check|Check OS version for each host in cluster|
|cpu_cores_check|Check CPU cores for each host in cluster|
|memory_size_check| Check RAM size for each host in cluster|
|diskspace_check| Check free diskspace for database data directory|
|host_load_check| Get `uptime` output for each host|
|segments_status_check|Check if there is any segments down. |
|standby_status_check|Check if the standby master is sync or not. |
|guc_check|Get current important GUCs setting|
|res_queue_check|Get resource queue setting. If no resource queue other than `pg_default` exists, check result shows `NOT OK`.|
|db_size_check|Get db size for all databases in cluster. **Note**: The DB size relies on the statstics. It could be inaccurate if the statistics are not up to date.|
|schema_size_check|Get all schemas size in each database. **Note**: The schema size relies on the statstics. It could be inaccurate if the statistics are not up to date.|
|table_size_check|Get top 100 size tables in each database. **Note**: The table size relies on the statstics. It could be inaccurate if the statistics are not up to date.|
|data_skew_check| - For CBDB: PAX tables are checked server-side with `gp_toolkit.gp_skew_coefficient` (called one table at a time to avoid exhausting the cluster DSM slots); AO/AOCS tables are checked by comparing on-disk file size across each segment (table size > `TABLE_SKEW_MIN_SIZE_GB` and max-min segment gap > `TABLE_SKEW_PERCENT`% → `NOT OK`). Files are mapped to tables using each segment's own catalog because `relfilenode` is not consistent between the coordinator and segments. - For 2x, check data skew by comparing the file size on OS across each segment. - For 3x, compare the rowcounts across the segments.|
|heap_table_bloat_check| For 2x and CBDB, get bloated heap table list.|
|ao_table_bloat_check|  Get the AO/AOCS bloated table list.|
|db_age_check| Check db age for each database across all segments. The result will be `NOT OK` if the age reaches the warn limit `2^31-1 - xid_stop_limit`.|
|temp_schema_check| Check master and all segments for any temp schemas existing.|
|pg_activity_check|Check current running queries in database. The check result will be `NOT OK` if any query runs > 1hr.|
|pg_locks_check| Check if there is any session holding the lock > 10mins.|
|stale_stats_check|Get a list of tables which have not been analyzed.|
