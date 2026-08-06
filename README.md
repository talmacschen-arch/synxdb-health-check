# synxdb-health-check

This tool can be used for health check on SynxDB and CBDB databases.

## Setup

### Prerequisites
1. A running SynxDB or CBDB database with `gpadmin` access.
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

2. Run the health check as `gpadmin`.

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
|IDLE_IN_TRANSACTION_THRESHOLD|The threshold for how long a session may sit in `idle in transaction` before `idle_in_transaction_check` reports it. (Default: 600s)|
|LOCK_HOLD_TIME|The lock time threshold for the `pg_locks_check`. (Default: 600s)|
|WITHOUT_ANALYZE_DAYS|The days for which tables have not been analyzed. (Default: 7 days)|
|TABLE_MIN_TUPLES_FOR_CHECK|Tables with rowcounts > `TABLE_MIN_TUPLES_FOR_CHECK` will be checked,e.g. bloat check, skew check..etc. (Default: 100000)|
|TABLE_BLOAT_PERCENT|The bloat percent the the `heap_table_bloat_check` and `ao_table_bloat_check`. (Default: 20%)|
|TABLE_SKEW_PERCENT|Skew threshold for the **max-min gap** metric used by the AO/AOCS file-size based skew check, i.e. `100*(max_seg-min_seg)/max_seg`. Tables above this are reported. (Default: 20%) |
|TABLE_SKEW_MIN_SIZE_GB|Minimum on-disk size (GB) for a table to be reported by the file-size based skew check (CBDB AO tables). (Default: 1GB) |
|TABLE_SKEW_CV_PERCENT|Skew threshold for the **coefficient of variation (CV)** metric used by the PAX skew check (`gp_toolkit.gp_skew_coefficient`, `stddev/avg` of per-segment row counts, on a percentage scale). This is a different metric from `TABLE_SKEW_PERCENT`'s max-min gap, so it has its own threshold, aligned with Greenplum's guidance that tables with more than 10% skew should have their distribution policy re-evaluated. (Default: 10%) |
|OS_OVERCOMMIT_MEMORY_EXPECTED|Expected `vm.overcommit_memory` value for `os_kernel_check`. Exposed as a knob because some resource-group deployments intentionally differ from Greenplum's recommended value. (Default: 2)|
|OS_ULIMIT_NOFILE_MIN|Minimum acceptable `ulimit -n` (open files) per host for `os_kernel_check`. (Default: 524288)|
|OS_ULIMIT_NPROC_MIN|Minimum acceptable `ulimit -u` (max user processes) per host for `os_kernel_check`. (Default: 131072)|
|CLOCK_SKEW_MAX_SEC|Maximum tolerated wall-clock skew (seconds) between hosts for `clock_sync_check`. Kept loose so the latency of sequential ssh calls is not mistaken for real skew. (Default: 5s)|


## Supported Check Items

| Check Item  | Description | 
|:------------|:------------|
|db_version_check|Check database version |
|seg_config_check| Get `gp_segment_configuration`|
|os_version_check|Check OS version for each host in cluster|
|os_kernel_check|Check GP-recommended OS kernel settings on each host: `vm.overcommit_memory` (expected `OS_OVERCOMMIT_MEMORY_EXPECTED`), Transparent Huge Pages disabled (`[never]`), `RemoveIPC=no`, and `ulimit` open-files / max-processes above `OS_ULIMIT_NOFILE_MIN` / `OS_ULIMIT_NPROC_MIN`. Any host failing any item makes the result `NOT OK`. Probed over the existing `ssh gpadmin@host` channel.|
|cpu_cores_check|Check CPU cores for each host in cluster|
|memory_size_check| Check RAM size for each host in cluster|
|diskspace_check| Check free diskspace for database data directory|
|host_load_check| Get `uptime` output for each host|
|clock_sync_check|Check host clock synchronization: each host's NTP sync state (`timedatectl` `NTPSynchronized`) and the wall-clock skew across hosts. The result is `NOT OK` if any host is not NTP-synchronized or the max-min skew exceeds `CLOCK_SKEW_MAX_SEC`. Clock skew can disrupt FTS and replication. Probed over the existing `ssh gpadmin@host` channel.|
|segments_status_check|Check if there is any segments down. |
|standby_status_check|Check if the standby master is sync or not. |
|seg_role_balance_check|Check `gp_segment_configuration` for segments whose current `role` differs from `preferred_role` (an FTS failover that never rebalanced, leaving one host with a double share of primaries) or, for data segments (`content >= 0`), whose `mode` is not `s` (still resyncing). The result is `NOT OK` if any such segment exists. The coordinator's own sync state is left to `standby_status_check`, so `mode` is only judged for `content >= 0` to avoid a false positive on mirrorless clusters.|
|guc_check|Get current important GUCs setting|
|res_queue_check|Get resource queue setting. If no resource queue other than `pg_default` exists, check result shows `NOT OK`. On CBDB/SynxDB this check only runs when the active resource manager (`gpconfig -s gp_resource_manager`) is `queue`; in a group mode it is skipped in favor of `resgroup_check`.|
|resgroup_check|Get resource group configuration from `gp_toolkit.gp_resgroup_config` together with the current `gp_resource_manager` mode. Only runs on CBDB/SynxDB when the active resource manager (`gpconfig -s gp_resource_manager`) is a group mode (`group`/`group-v2`); in `queue` mode it is skipped in favor of `res_queue_check`. If in a group mode but no user-defined resource group exists besides the built-in `default_group`/`admin_group`/`system_group`, the result is `NOT OK`.|
|db_size_check|Get db size for all databases in cluster. **Note**: The DB size relies on the statstics. It could be inaccurate if the statistics are not up to date.|
|schema_size_check|Get all schemas size in each database. **Note**: The schema size relies on the statstics. It could be inaccurate if the statistics are not up to date.|
|table_size_check|Get top 100 size tables in each database, aggregated by logical table: leaf partitions are rolled up to their root partitioned table via `pg_partition_root` so a large partitioned table is ranked as a single entry instead of scattered per-partition. Sizes come from `relpages`; tables that have never been analyzed (`relpages = -1`) fall back to `pg_relation_size` so they are not silently dropped as size 0. **Note**: For analyzed tables the size still relies on the statistics and could be inaccurate if they are not up to date.|
|data_skew_check| - For CBDB, PAX and AO/AOCS tables use **different skew metrics with different thresholds**: <br> • **PAX**: checked server-side with `gp_toolkit.gp_skew_coefficient` (called one table at a time to avoid exhausting the cluster DSM slots). `skccoeff` is the coefficient of variation (`stddev/avg` of per-segment row counts, on a percentage scale); `skccoeff > TABLE_SKEW_CV_PERCENT` → `NOT OK`. <br> • **AO/AOCS**: checked by comparing on-disk file size across each segment; table size > `TABLE_SKEW_MIN_SIZE_GB` and max-min segment gap `100*(max-min)/max` > `TABLE_SKEW_PERCENT`% → `NOT OK`. Files are mapped to tables using each segment's own catalog because `relfilenode` is not consistent between the coordinator and segments. <br> Note the two metrics are not the same unit: for a given table the CV is typically smaller than the max-min gap, which is why they use separate thresholds (`TABLE_SKEW_CV_PERCENT` vs `TABLE_SKEW_PERCENT`).|
|heap_table_bloat_check| For CBDB, get bloated heap table list.|
|ao_table_bloat_check|  Get the AO/AOCS bloated table list.|
|db_age_check| Check db age for each database across all segments. The result will be `NOT OK` if the age reaches the warn limit `2^31-1 - xid_stop_limit`.|
|db_mxid_age_check| Check the multixact age (`mxid_age(datminmxid)`) for each database across all segments. Multixact wraparound is an independent risk line from the plain XID age of `db_age_check` — a healthy `datfrozenxid` age does not imply a healthy multixact age. Uses the same warn/stop limit logic as `db_age_check`; the result is `NOT OK` if any database reaches the warn limit.|
|temp_schema_check| Check master and all segments for any temp schemas existing.|
|pg_activity_check|Check current running queries in database. The check result will be `NOT OK` if any query runs > 1hr.|
|idle_in_transaction_check|Check for sessions sitting in `idle in transaction` (or `idle in transaction (aborted)`) longer than `IDLE_IN_TRANSACTION_THRESHOLD`, measured from `xact_start`. Such sessions hold back the global xmin, blocking vacuum and inflating XID/multixact age and bloat. The result is `NOT OK` if any such session exists.|
|pg_locks_check| Check if there is any session holding the lock > 10mins.|
|stale_stats_check|Get a list of tables which have not been analyzed.|
|invalid_index_check|Check each database for indexes left in an unusable state — `indisvalid = false` (e.g. a failed `CREATE INDEX CONCURRENTLY`) or `indisready = false` (interrupted mid-build). The planner silently ignores such indexes, so queries degrade with no error. The result is `NOT OK` if any invalid index exists.|


## Changelog

- **Fix whole-run crash in the bloated-AO-tables check on live clusters.** `ao_table_bloat_check` computed `gp_toolkit.__gp_aovisimap_compaction_info(oid)` for every AO/AOCO table inside one query. That function opens each relation's visimap, so a concurrent `DELETE`/`VACUUM`/`DROP` on *any single* AO table during the scan aborted the whole statement with `ERROR: could not open relation with OID … (This can be validly caused by a concurrent delete operation on this object.)`, crashing the entire health check. The candidate tables are now listed first and each is probed in its own statement; a table that hits the concurrency race is rolled back and skipped (and reported in a `… skipped due to concurrent activity` note) so the rest of the check completes. Detection results for unaffected tables are unchanged.
- **Fix `public.mpp_table_size` view re-creation failing after the `size_mb` type change.** The previous fix widened `size_mb` to `bigint`, but the view was still (re)built with `CREATE OR REPLACE VIEW`, which cannot change an existing column's data type — so on any cluster where a prior run had left the old `integer`-typed view, every run aborted with `ERROR: cannot change data type of view column "size_mb" from integer to bigint`. The view is now `DROP VIEW IF EXISTS … ; CREATE VIEW …` so it is rebuilt cleanly regardless of the pre-existing definition.
- **Fix division by zero in the bloated-heap-tables check.** `heap_table_bloat_check` divided by `bdirelpages` in both the `WHERE` and `ORDER BY` of its `gp_toolkit.gp_bloat_diag` query. Although the view only emits rows with `bdirelpages > 0`, the planner inlines it and evaluates the outer division against the underlying `gp_bloat_expected_pages` feeder rows — which include tables with `relpages = 0` (e.g. a table analyzed and then truncated) — *before* the view's own `bltidx > 0` filter applies, raising `ERROR: division by zero` and aborting the whole run. Both denominators are now guarded with `nullif(bdirelpages, 0)`; results for real bloat rows (which always have `bdirelpages > 0`) are unchanged.
- **Fix integer overflow in the `public.mpp_table_size` view for very large tables.** The `size_mb` expression computed `c.relpages * 32 / 1024` in `int4` arithmetic, so `relpages * 32` overflowed once `relpages` exceeded ~67M pages — a heap table of roughly 2 TB at the 32 KB block size — raising `ERROR: integer out of range` and aborting the Database Size check (and every other check that reads the view). `relpages` is now cast to `bigint` before the multiplication and the whole `size_mb` column is `bigint`.
- **Fix clock-skew note placement in the HTML Host Clock Sync report.** In the `html` report, the *Host Clock Sync* table is rendered with `align="left"`, which floats it, so the `Max clock skew across hosts: …` summary — appended with only a `<br>` — flowed to the right of the floated table instead of below it (`<br>` cannot clear a float). The note is now wrapped in `<p style="clear:both">` so it renders on its own line below the table. The `text` report was unaffected.
- **Add OS kernel-parameter and host clock-sync checks.** `os_kernel_check` verifies the GP-recommended OS settings on each host — `vm.overcommit_memory` (expected value configurable via `OS_OVERCOMMIT_MEMORY_EXPECTED`), Transparent Huge Pages disabled, `RemoveIPC=no`, and `ulimit` open-files / max-processes minimums — since node drift on these silently degrades the cluster. `clock_sync_check` verifies each host is NTP-synchronized and that the wall-clock skew across hosts stays within `CLOCK_SKEW_MAX_SEC`, because clock skew disrupts FTS and replication. Both reuse the existing `ssh gpadmin@host` channel.
- **Scope `pg_activity_check` to actively-running client queries.** The long-running query check now reports only backends with `state = 'active'` and `backend_type = 'client backend'`. Background and replication connections — such as the standby WAL sender's permanent `START_REPLICATION` — and idle client sessions are no longer counted as long-running queries. `idle in transaction` sessions remain covered by `idle_in_transaction_check`.
- **Report long-running queries and long-held locks by total elapsed time.** `pg_activity_check` and `pg_locks_check` now measure elapsed time with `extract(epoch from now()-query_start)`, so a query running longer than `LONG_RUNNING_QUERY_THRESHOLD` (default 1hr) or a lock held longer than `LOCK_HOLD_TIME` (default 10min) is reported as intended, and the reported `duration_sec` / `lock_duration_sec` is the whole elapsed seconds.
- **Add four health-check items based on GP7 inspection best practices.** `seg_role_balance_check` flags segments whose current `role` differs from `preferred_role` (unrebalanced FTS failover) or data segments still resyncing (`mode <> 's'`). `db_mxid_age_check` checks multixact wraparound age (`mxid_age(datminmxid)`), an independent risk line from the XID age already covered by `db_age_check`. `idle_in_transaction_check` reports sessions stuck in `idle in transaction` longer than `IDLE_IN_TRANSACTION_THRESHOLD` (holding back the global xmin). `invalid_index_check` reports indexes with `indisvalid = false` / `indisready = false`, which the planner silently ignores. All four are pure SQL with no external dependencies.
- **Fix text report summary table rendering.** In the `text` (`.rpt`) report, the *Database Check Summary* table previously rendered with empty data cells (`|      |`) while the header and all detail tables were fine. The ANSI color-stripping step used a greedy pattern (`\033\[.*m`) that, on a colored summary row, deleted the cell text and column separators between the first and last escape code. The pattern is now anchored to the escape sequence (`\033\[[0-9;]*m`) so only the color codes are stripped.
- **Give the PAX skew check its own threshold.** `data_skew_check` compared `gp_toolkit.gp_skew_coefficient`'s `skccoeff` (a coefficient of variation, `stddev/avg` of per-segment row counts) against `TABLE_SKEW_PERCENT`, the same value used for the AO/AOCS max-min gap metric. Because the CV is a different (typically smaller) metric than the gap, PAX tables were effectively judged more leniently. A dedicated `TABLE_SKEW_CV_PERCENT` (default 10, aligned with Greenplum's guidance to re-evaluate distribution above 10% skew) now controls the PAX/CV path; the AO/AOCS gap path keeps `TABLE_SKEW_PERCENT`.
- **Fix `table_size_check` missing large partitioned and un-analyzed tables.** Top-100 table sizes are now aggregated by logical table — leaf partitions are rolled up to their root via `pg_partition_root` instead of ranking each partition separately, so a large partitioned table appears as a single entry. Tables that have never been analyzed (`relpages = -1`) now fall back to `pg_relation_size` instead of being dropped as size 0.
