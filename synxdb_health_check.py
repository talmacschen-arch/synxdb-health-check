#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
@author: Liang
"""

import subprocess
import sys
import os
import time
import codecs
import yaml
import re
import argparse
from datetime import datetime
from prettytable import PrettyTable
try: 
    from pygresql import pgdb
except:
    pass
try:
    import pgdb
except:
    pass

##################  SQL Parameters ################## 
MASTER_HOST_NAME='localhost'
MASTER_PORT=5432
LONG_RUNNING_QUERY_THRESHOLD=3600
LOCK_HOLD_TIME=600
WITHOUT_ANALYZE_DAYS=7
TABLE_MIN_TUPLES_FOR_CHECK=100000
TABLE_BLOAT_PERCENT=20
TABLE_UPDATE_COUNT_3X=50000
TABLE_SKEW_PERCENT=20
TABLE_SKEW_MIN_SIZE_GB=1
TABLE_SKEW_CV_PERCENT=10

##################  SQL queries ################## 
get_db_version_sql = 'select version()'
get_db_names_sql = '''select datname from pg_database where datname not in ('template0','template1','postgres')'''
get_segment_config_sql = 'select dbid,content,role,preferred_role,mode,status,port,hostname,address from gp_segment_configuration order by dbid'
get_hosts_sql = 'select distinct(hostname) as hostname from gp_segment_configuration order by hostname'
# Union of the health-check's historical GUC list and the parameters shown on
# the DBCC console (dbcc-core-server application-guc.configuration.yml). Both
# coordinator and segment values are reported, matching the DBCC console.
# The parameter names drive the query via a VALUES list and LEFT JOINs so that
# a parameter absent in the running version (e.g. legacy GPDB GUCs removed in
# PG14/SynxDB4) is still listed, with blank values, instead of silently dropped.
# coordinator_value comes from pg_settings (this connection is on the coordinator);
# segment_value comes from gp_toolkit.gp_param_settings() for segment content 0.
get_guc_sql = '''
SELECT p.name AS name,
       COALESCE(c.setting, '') AS coordinator_value,
       COALESCE(s.paramvalue, '') AS segment_value
FROM (VALUES
 ('autovacuum')
,('default_statistics_target')
,('gp_appendonly_insert_files')
,('gp_autostats_mode')
,('gp_autostats_on_change_threshold')
,('gp_enable_runtime_filter_pushdown')
,('gp_external_enable_exec')
,('gp_external_max_segs')
,('gp_fts_probe_interval')
,('gp_fts_probe_timeout')
,('gp_interconnect_queue_depth')
,('gp_interconnect_snd_queue_depth')
,('gp_interconnect_tcp_listener_backlog')
,('gp_interconnect_type')
,('gp_resqueue_priority_cpucores_per_segment')
,('gp_segment_connect_timeout')
,('gp_vmem_protect_limit')
,('gp_workfile_compress_algorithm')
,('gp_workfile_limit_files_per_query')
,('gp_workfile_limit_per_query')
,('gp_workfile_limit_per_segment')
,('join_collapse_limit')
,('log_duration')
,('log_statement')
,('max_appendonly_tables')
,('max_connections')
,('max_prepared_transactions')
,('max_stack_depth')
,('max_statement_mem')
,('optimizer')
,('password_encryption')
,('pg_gophermeta.register_gophermeta')
,('shared_buffers')
,('statement_mem')
,('statement_timeout')
,('superuser_reserved_connections')
,('work_mem')
) AS p(name)
LEFT JOIN pg_settings AS c ON c.name = p.name
LEFT JOIN gp_toolkit.gp_param_settings() AS s ON s.paramname = p.name AND s.paramsegment = 0
ORDER BY p.name
'''
get_resqueue_sql = 'SELECT * FROM gp_toolkit.gp_resqueue_status'
get_resgroup_sql = 'SELECT * FROM gp_toolkit.gp_resgroup_config'
get_resource_manager_sql = 'show gp_resource_manager'
get_resource_manager_gpconfig_cmd = 'gpconfig -s gp_resource_manager'
check_standby_sql_pg9 = 'SELECT pid, state FROM pg_stat_replication'
check_standby_sql_pg8 = 'SELECT procpid, state FROM pg_stat_replication'
get_pg_activity_sql_pg14 = '''
select datname,pid,sess_id,usename,application_name,client_addr,client_hostname,backend_start,xact_start,query_start,extract(epoch from now()-query_start)::int as duration_sec,wait_event,state,query,wait_event_type,rsgname 
from pg_stat_activity
where extract(epoch from now()-query_start) > {0}
'''.format(LONG_RUNNING_QUERY_THRESHOLD)
get_pg_activity_sql_pg9 = '''
select datname,pid,sess_id,usename,application_name,client_addr,client_hostname,backend_start,xact_start,query_start,extract(epoch from now()-query_start)::int as duration_sec,waiting,state,query,waiting_reason,rsgname,rsgqueueduration 
from pg_stat_activity
where extract(epoch from now()-query_start) > {0}
'''.format(LONG_RUNNING_QUERY_THRESHOLD)
get_pg_activity_sql_pg8 = '''
select datname,procpid,sess_id,usename,application_name,client_addr,backend_start,xact_start,query_start,extract(epoch from now()-query_start)::int as duration_sec,waiting,current_query,waiting_reason,rsgname,rsgqueueduration 
from pg_stat_activity
where extract(epoch from now()-query_start) > {0}
'''.format(LONG_RUNNING_QUERY_THRESHOLD)
get_pg_locks_sql_pg9 = '''
select a.gp_segment_id, a.pid, a.mode, a.mppsessionid, c.nspname,b.relname, extract(epoch from now()-d.query_start)::int as lock_duration_sec, d.query as query_hold_lock
from pg_locks a, pg_class b, pg_namespace c, pg_stat_activity d
where a.relation=b.oid and b.relnamespace=c.oid
and a.locktype='relation' and granted = 't' 
and a.mppsessionid = d.sess_id
and extract(epoch from now()-d.query_start) > {0}
and relation in (select relation from pg_locks where granted = 'f')
order by gp_segment_id
'''.format(LOCK_HOLD_TIME)
get_pg_locks_sql_pg8 = '''
select a.gp_segment_id, a.pid, a.mode, a.mppsessionid, c.nspname,b.relname, extract(epoch from now()-d.query_start)::int as lock_duration_sec, d.current_query as query_hold_lock
from pg_locks a, pg_class b, pg_namespace c, pg_stat_activity d
where a.relation=b.oid and b.relnamespace=c.oid
and a.locktype='relation' and granted = 't' 
and a.mppsessionid = d.sess_id
and extract(epoch from now()-d.query_start) > {0}
and relation in (select relation from pg_locks where granted = 'f')
order by gp_segment_id
'''.format(LOCK_HOLD_TIME)
get_diskspace_sql = '''
SELECT distinct dfhostname, dfdevice, (dfspace/1024/1024)::decimal(18,2) as "space_avail_gb" FROM gp_toolkit.gp_disk_free order by dfhostname
'''
create_mpp_table_size_view_sql = '''
create or replace view public.mpp_table_size
as select c.oid,n.nspname as schemaname,c.relname as tablename,
(case when c.relpages > 0 then c.relpages * 32/1024
      else (pg_relation_size(c.oid)/1024/1024)::int end) as size_mb
from pg_class c join pg_namespace n on c.relnamespace=n.oid
where c.relkind='r'
'''
get_db_size_sql = '''select round(sum(size_mb)/1024.0,2) as db_size_gb from public.mpp_table_size where schemaname not like 'pg\_%'
'''
get_schema_size_sql = '''
select  a.schemaname,a.table_count,round(b.size_gb,2) as size_gb from (select schemaname,count(*) as table_count from pg_tables group by 1 )a 
left join
 (Select schemaname ,sum(size_mb)/1024.0 as size_gb  from  public.mpp_table_size  group by 1) b
 on a.schemaname=b.schemaname
where a.schemaname not like 'pg_%' order by  3 desc
'''
get_table_size_sql = '''
select schemaname,tablename,size_mb from (
  select
    coalesce(rc.nspname, v.schemaname) as schemaname,
    coalesce(rc.relname, v.tablename)  as tablename,
    sum(v.size_mb) as size_mb
  from public.mpp_table_size v
  left join lateral (
    select n2.nspname, c2.relname
    from pg_class c2 join pg_namespace n2 on c2.relnamespace=n2.oid
    where c2.oid = pg_partition_root(v.oid)
  ) rc on true
  group by 1,2
) t
where schemaname not like 'pg\_%' and size_mb > 0 order by 3 desc limit 100
'''
create_data_skew_fn_sql = """
CREATE OR REPLACE FUNCTION public.fn_get_skew(out schema_name      varchar,
                                              out table_name       varchar,
                                              out pTableName       varchar,
                                              out total_size_GB    numeric(15,2),
                                              out seg_min_size_GB  numeric(15,2),
                                              out seg_max_size_GB  numeric(15,2),
                                              out seg_avg_size_GB  numeric(15,2),
                                              out seg_gap_min_max_percent numeric(6,2),
                                              out seg_gap_min_max_GB      numeric(15,2),
                                              out nb_empty_seg     int) RETURNS SETOF record AS
$$
DECLARE
    v_function_name text := 'fn_get_skew';
    v_location int;
    v_sql text;
    v_db_oid text;
    v_num_segments numeric;
    v_skew_amount numeric;
    v_res record;
BEGIN
    v_location := 1000;
    SELECT oid INTO v_db_oid
    FROM pg_database
    WHERE datname = current_database();

    v_location := 2200;
    v_sql := 'DROP EXTERNAL TABLE IF EXISTS public.db_files_ext';

    v_location := 2300;
    EXECUTE v_sql;

    v_location := 3000;
    v_sql := 'CREATE EXTERNAL WEB TABLE public.db_files_ext ' ||
            '(segment_id int, relfilenode text, filename text, ' ||
            'size numeric) ' ||
            'execute E''ls -l $GP_SEG_DATADIR/base/' || v_db_oid ||
            ' | ' ||
            'grep gpadmin | ' ||
            E'awk {''''print ENVIRON["GP_SEGMENT_ID"] "\\t" $9 "\\t" ' ||
            'ENVIRON["GP_SEG_DATADIR"] "/' || v_db_oid ||
            E'/" $9 "\\t" $5''''}'' on all ' || 'format ''text''';

    v_location := 3100;
    EXECUTE v_sql;

    v_location := 4000;
    for v_res in (
                select  sub.vschema_name,
                        sub.vtable_name,
                        (sum(sub.size)/(1024^3))::numeric(15,2) AS vtotal_size_GB,
                        --Size on segments
                        (min(sub.size)/(1024^3))::numeric(15,2) as vseg_min_size_GB,
                        (max(sub.size)/(1024^3))::numeric(15,2) as vseg_max_size_GB,
                        (avg(sub.size)/(1024^3))::numeric(15,2) as vseg_avg_size_GB,
                        --Percentage of gap between smaller segment and bigger segment
                        (100*(max(sub.size) - min(sub.size))/greatest(max(sub.size),1))::numeric(6,2) as vseg_gap_min_max_percent,
                        ((max(sub.size) - min(sub.size))/(1024^3))::numeric(15,2) as vseg_gap_min_max_GB,
                        count(sub.size) filter (where sub.size = 0) as vnb_empty_seg
                    from (
                        SELECT  n.nspname AS vschema_name,
                                c.relname AS vtable_name,
                                db.segment_id,
                                sum(db.size) AS size
                            FROM ONLY public.db_files_ext db
                                JOIN pg_class c ON split_part(db.relfilenode, '.'::text, 1) = c.relfilenode::text
                                JOIN pg_namespace n ON c.relnamespace = n.oid
                            WHERE c.relkind = 'r'::"char"
                                and n.nspname not in ('pg_catalog','information_schema','gp_toolkit')
                                and not n.nspname like 'pg_temp%'
                            GROUP BY n.nspname, c.relname, db.segment_id
                        ) sub
                    group by 1,2
                    --Extract only table bigger than 1 GB
                    --   and with a skew greater than 20%
                    having sum(sub.size)/(1024^3) > 1
                        and (100*(max(sub.size) - min(sub.size))/greatest(max(sub.size),1))::numeric(6,2) > 20
                    order by vtotal_size_GB desc, vseg_gap_min_max_percent desc
                    limit 100 ) loop
        schema_name         = v_res.vschema_name;
        table_name          = v_res.vtable_name;
        total_size_GB       = v_res.vtotal_size_GB;
        seg_min_size_GB     = v_res.vseg_min_size_GB;
        seg_max_size_GB     = v_res.vseg_max_size_GB;
        seg_avg_size_GB     = v_res.vseg_avg_size_GB;
        seg_gap_min_max_percent = v_res.vseg_gap_min_max_percent;
        seg_gap_min_max_GB  = v_res.vseg_gap_min_max_GB;
        nb_empty_seg        = v_res.vnb_empty_seg;
        return next;
    end loop;

    v_location := 4100;
    v_sql := 'DROP EXTERNAL TABLE IF EXISTS public.db_files_ext';

    v_location := 4200;
    EXECUTE v_sql;

    return;
EXCEPTION
        WHEN OTHERS THEN
                RAISE EXCEPTION '(%:%:%)', v_function_name, v_location, sqlerrm;
END;
$$
language plpgsql;
"""
get_data_skew_sql = 'select * from public.fn_get_skew()'
get_ao_data_skew_sql = '''
select max(gp_segment_id), min(seg_count),max(seg_count),sum(seg_count) from (select  gp_segment_id,count(*)  as seg_count from gp_dist_random(%s) group by 1) a; 
'''
get_db_age_sql = '''
WITH cluster AS (
	SELECT gp_segment_id, datname, age(datfrozenxid) age FROM pg_database
	UNION ALL
	SELECT gp_segment_id, datname, age(datfrozenxid) age FROM gp_dist_random('pg_database')
)
SELECT  gp_segment_id, datname, age,
        CASE
                WHEN age < (2^31-1 - current_setting('xid_stop_limit')::int - current_setting('xid_warn_limit')::int) THEN 'BELOW WARN LIMIT'
                WHEN  ((2^31-1 - current_setting('xid_stop_limit')::int - current_setting('xid_warn_limit')::int) < age) AND (age <  (2^31-1 - current_setting('xid_stop_limit')::int)) THEN 'OVER WARN LIMIT and UNDER STOP LIMIT'
                WHEN age > (2^31-1 - current_setting('xid_stop_limit')::int ) THEN 'OVER STOP LIMIT'
                WHEN age < 0 THEN 'OVER WRAPAROUND'
        END
FROM cluster
ORDER BY datname, gp_segment_id
'''
get_temp_schema_sql = '''
select nspname from pg_namespace where nspname like 'pg_temp%' except select 'pg_temp_' || sess_id::varchar from pg_stat_activity
union
select nspname from gp_dist_random('pg_namespace') where nspname like 'pg_temp%' except select 'pg_temp_' || sess_id::varchar from pg_stat_activity
'''
get_stale_stats_sql = '''select schemaname,s.relname,last_vacuum,last_analyze,last_autoanalyze
from pg_stat_all_tables s join pg_class c
on s.relid = c.oid
where schemaname not in ('pg_toast','pg_catalog','information_schema','gp_toolkit')
and reltuples > {0}
and schemaname !~ '^pg_toast'
and s.relname not like '%prt%'
and COALESCE(last_vacuum,'2022-01-01',last_vacuum) < now() - interval '{1} day' 
and COALESCE(last_analyze,'2022-01-01',last_analyze) < now() - interval '{1} day'
and COALESCE(last_autoanalyze,'2022-01-01',last_analyze) < now() - interval '{1} day'
order by schemaname, relname
'''.format(TABLE_MIN_TUPLES_FOR_CHECK, WITHOUT_ANALYZE_DAYS)
get_heap_bloat_sql = 'select * from gp_toolkit.gp_bloat_diag where bdiexppages*100/bdirelpages <={0} order by bdiexppages/bdirelpages desc limit 20'.format(TABLE_BLOAT_PERCENT)
get_legacy2_ao_bloat_sql = '''
select * from (
SELECT 
c.oid, 
n.nspname AS schema_name, 
c.relname AS table_name, 
c.reltuples::bigint AS num_rows, 
(SELECT max(percent_hidden) FROM gp_toolkit.__gp_aovisimap_compaction_info(c.oid)) as percent_hidden, 
(SELECT sum(total_tupcount) FROM gp_toolkit.__gp_aovisimap_compaction_info(c.oid)) as total_tupcount, 
(SELECT sum(hidden_tupcount) FROM gp_toolkit.__gp_aovisimap_compaction_info(c.oid))  as hidden_tupcount 
FROM pg_appendonly a 
JOIN pg_class c ON c.oid=a.relid 
JOIN pg_namespace n ON c.relnamespace=n.oid 
where c.reltuples > {0}
) as ao_bloat
where percent_hidden > {1}
'''.format(TABLE_MIN_TUPLES_FOR_CHECK, TABLE_BLOAT_PERCENT)
get_ao_table_list_sql = '''
select n.nspname as schemaname,c.relname as tablename ,ap.segrelid::regclass as ao_table from pg_class c join pg_namespace n on c.relnamespace=n.oid join pg_appendonly ap on c.oid=ap.relid where c.relkind='r' and c.reltuples > {0} and n.nspname  not like 'pg_%'
'''.format(TABLE_MIN_TUPLES_FOR_CHECK)
get_legacy3_ao_bloat_sql_base = 'select sum(extraindexnum) from '

get_db_oid_sql = 'select oid from pg_database where datname = current_database()'

# External table that lists each segment's data files (and their size) under base/<dboid>.
create_db_files_ext_sql = r'''CREATE EXTERNAL WEB TABLE public.db_files_ext (segment_id int, relfilenode text, filename text, size numeric) execute E'ls -l $GP_SEG_DATADIR/base/{0} | grep gpadmin | awk {{''print ENVIRON["GP_SEGMENT_ID"] "\t" $9 "\t" ENVIRON["GP_SEG_DATADIR"] "/{0}/" $9 "\t" $5''}}' on all format 'text' '''

# AO (ao_row/ao_column) skew by on-disk file size (the old, fastest method).
# Key fix: files must be mapped to tables via each segment's OWN catalog
# (gp_dist_random('pg_class')), joined on (segment_id, relfilenode), because on
# Cloudberry/SynxDB relfilenode is not consistent between the coordinator and
# the segments. The old code joined segment files to the coordinator's
# relfilenode, matched almost no large table, and silently reported "no skew"
# (a false empty).
get_ao_size_skew_sql = '''
with fileagg as (
    select segment_id, split_part(relfilenode, '.', 1) as rfn, sum(size) as seg_size
    from ONLY public.db_files_ext
    group by 1, 2
),
segcat as (
    select gp_segment_id, relfilenode::text as rfn, relname, relnamespace
    from gp_dist_random('pg_class') where relkind = 'r'
),
tbl as (
    select n.nspname as schema_name, sc.relname as table_name, f.segment_id, f.seg_size
    from fileagg f
    join segcat sc on sc.gp_segment_id = f.segment_id and sc.rfn = f.rfn
    join pg_namespace n on sc.relnamespace = n.oid
)
select t.schema_name, t.table_name, am.amname as storage,
       (100 * (max(t.seg_size) - min(t.seg_size)) / greatest(max(t.seg_size), 1))::numeric(6,2) as skew_percent
from tbl t
join pg_class c on c.relname = t.table_name
join pg_namespace cn on c.relnamespace = cn.oid and cn.nspname = t.schema_name
join pg_appendonly aoo on aoo.relid = c.oid
join pg_am am on c.relam = am.oid
group by 1, 2, 3
having (100 * (max(t.seg_size) - min(t.seg_size)) / greatest(max(t.seg_size), 1)) > {0}
   and sum(t.seg_size) > {1} * 1024 ^ 3
order by skew_percent desc
'''.format(TABLE_SKEW_PERCENT, TABLE_SKEW_MIN_SIZE_GB)

# PAX tables cannot be sized from the base/<dboid> file listing (PAX stores its
# data in per-relation directories), so distribution skew is read server-side
# with gp_toolkit.gp_skew_coefficient(). It must be called one table at a time:
# the gp_skew_coefficients view walks every user table and allocates a DSM
# segment per table x per segment, which exhausts the cluster-wide DSM slots
# ("too many dynamic shared memory segments") on databases with many tables.
# Per-table calls avoid this.
get_pax_table_list_sql = '''
select n.nspname, c.relname, c.oid
from pg_class c
join pg_namespace n on c.relnamespace = n.oid
join pg_am am on c.relam = am.oid
where c.relkind = 'r' and am.amname = 'pax' and c.reltuples > {0}
  and n.nspname not in ('pg_catalog', 'information_schema', 'gp_toolkit')
  and n.nspname not like 'pg_temp%'
order by n.nspname, c.relname
'''.format(TABLE_MIN_TUPLES_FOR_CHECK)

get_skew_coefficient_sql = 'select (gp_toolkit.gp_skew_coefficient(%s)).skccoeff'

################## Common functions ################## 
def execSQL(conn,sql,params=''):
    cursor=conn.cursor()
    cursor.execute(sql,params)
    return cursor

def get_hosts_list(dbconn):
    hosts = execSQL(dbconn,get_hosts_sql)
    hosts_list = [row[0] for row in hosts]
    return hosts_list

def get_db_list(dbconn):
    cursor = execSQL(dbconn,get_db_names_sql)
    db_names_list = cursor.fetchall()
    return [row[0] for row in db_names_list]

def get_pg_version(dbconn):
    cursor = execSQL(dbconn, 'select version()')
    pg_version = cursor.fetchone()
    if 'Cloudberry' in pg_version[0]:
        pg_kernal = 'cbdb'
    return pg_kernal

def _execute_shell_command(bash_command):
    try:
        output = subprocess.check_output(bash_command, shell=True).decode().rstrip()
    except subprocess.CalledProcessError as e:
        output = str(e)
    return output

def get_resource_manager_mode(dbconn):
    # Prefer the cluster-wide persisted value from gpconfig; the coordinator
    # (a.k.a. master on older versions) value is authoritative here.
    mode = ''
    gpconfig_output = _execute_shell_command(get_resource_manager_gpconfig_cmd)
    for line in gpconfig_output.splitlines():
        matched = re.search(r'(?:Coordinator|Master)\s+value:\s*(\S+)', line)
        if matched:
            mode = matched.group(1)
            break
    # Fall back to the session GUC if gpconfig output could not be parsed.
    if not mode:
        cursor = execSQL(dbconn, get_resource_manager_sql)
        mode = cursor.fetchone()[0]
    return mode

def check_items_output(check_item, check_result, check_result_detail, rpt_format):
    green_print_flag = '\033[1;32m'
    red_print_flag = '\033[1;31m'
    color_print_end_flag = '\033[0m'
    html_color = ''
    color_print_start_flag = ''
    if check_result == 'OK':
        color_print_start_flag = green_print_flag
        html_color = 'green'
    if 'NOT OK' in check_result:
        color_print_start_flag = red_print_flag
        html_color = 'red'
    if rpt_format == 'text':
        check_details_output = '\n\n### Check: ' + check_item + '\n\n' + color_print_start_flag + 'Result:\n    ' + check_result + color_print_end_flag + '\n\nDetails:\n'
        check_result_detail_indent_list = ['    ' + line for line in check_result_detail.splitlines()]
        check_result_detail_indent = '\n'.join(check_result_detail_indent_list)
        check_details_output += check_result_detail_indent
    if rpt_format == 'html':
        check_details_output = '''
        <div style="clear:both">
            <p>
            <br>
            <h3 style="text-align:left; margin:0; padding:0;">Check: %s</h3>
            <font color=%s><b>Result: %s</b></font>
            <br>
            <b>Details:</b>
            <br> 
            %s
            <br>
            </p>
        </div>
        ''' % (check_item,html_color,check_result,check_result_detail)
    return check_details_output

################## Health check items ################## 
def get_db_version(dbconn,rpt_format):
    check_item = 'Database Version'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn, get_db_version_sql)
    db_version_result = cursor.fetchone()
    db_version = db_version_result[0].split('on')[0]
    db_version_table = PrettyTable(['DB Version'])
    db_version_table.add_row([db_version])
    if rpt_format == 'text': 
        check_result_detail = db_version_table.get_string()
    if rpt_format == 'html':
        check_result_detail = db_version_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    db_version_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, db_version_output)

def seg_config_check(dbconn,rpt_format):
    check_item = 'Cluster Configuration'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn,get_segment_config_sql)
    seg_configs = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    check_result_table = PrettyTable(column_names_list)
    for row in seg_configs:
        check_result_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    seg_configs_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, seg_configs_check_output)

def os_version_check(hosts_list,rpt_format):
    check_item = 'OS Version'
    check_result = 'OK'
    os_version_check_list= []
    check_result_table = PrettyTable(["Host","OS version"])
    for host in hosts_list:
        os_version_cmd = 'ssh gpadmin@%s "cat /etc/os-release | grep PRETTY_NAME | cut -f2 -d ="' % (host)
        os_version_output = _execute_shell_command(os_version_cmd)
        os_version_check_list.append(os_version_output)
        check_result_table.add_row([host,os_version_output])
    if len(set(os_version_check_list)) != 1:
        check_result = 'NOT OK'
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    os_version_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, os_version_check_output)   

def cpu_cores_check(hosts_list,rpt_format):
    check_item = 'CPU Cores'
    check_result = 'OK'
    cpu_cores_check_list= []
    check_result_table = PrettyTable(["Host","CPU Cores"])
    for host in hosts_list:
        cpu_cores_cmd = 'ssh gpadmin@%s "cat /proc/cpuinfo| grep "processor"| wc -l"' % (host)
        cpu_cores_output = _execute_shell_command(cpu_cores_cmd)
        cpu_cores_check_list.append(cpu_cores_output)
        check_result_table.add_row([host,cpu_cores_output])
    if len(set(cpu_cores_check_list)) != 1:
        check_result = 'NOT OK'
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    cpu_cores_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, cpu_cores_check_output)   

def memory_size_check(hosts_list,rpt_format):
    check_item = 'Memory Size'
    check_result = 'OK'
    memory_size_check_list= []
    check_result_table = PrettyTable(["Host","Memory Size"])
    for host in hosts_list:
        memory_size_check_cmd = 'ssh gpadmin@%s "free -g" | grep Mem | awk \'{print $2}\'' % (host)
        memory_size_check_output = _execute_shell_command(memory_size_check_cmd)
        memory_size_check_list.append(memory_size_check_output)
        check_result_table.add_row([host,memory_size_check_output + 'GB'])
    if len(set(memory_size_check_list)) != 1:
        check_result = 'NOT OK'
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    memory_size_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, memory_size_check_output)   

def diskspace_check(dbconn,rpt_format):
    check_item = 'Disk Space'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn,get_diskspace_sql)
    diskspace_result = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    check_result_table = PrettyTable(column_names_list)
    for row in diskspace_result:
        if row[-1] < 10:
            check_result = 'NOT OK'
        check_result_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    diskspace_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, diskspace_check_output)

def host_load_check(hosts_list,rpt_format):
    check_item = 'Hosts Load'
    check_result = 'OK'
    check_result_detail = ''
    all_hosts_uptime_list = []
    for host in hosts_list:
        cpu_cores_cmd = 'ssh gpadmin@%s "cat /proc/cpuinfo| grep "processor"| wc -l"' % (host)
        cpu_cores_output = _execute_shell_command(cpu_cores_cmd)
        uptime_cmd = 'ssh gpadmin@%s "uptime"' % (host)
        uptime_output = _execute_shell_command(uptime_cmd).replace('\n', '') + '\n'
        uptime_output_list = [host] + uptime_output.split(',')
        if uptime_output_list[-1] > cpu_cores_output:
            check_result = 'NOT OK'
        all_hosts_uptime_list.append(uptime_output_list)
    all_hosts_uptime_list.sort(key=lambda x: x[-1], reverse=True)
    hosts_load_table = PrettyTable(['host','load'])
    for host in all_hosts_uptime_list:
        hosts_load_table.add_row([host[0],','.join(host[1:])])
    if rpt_format == 'text': 
        check_result_detail = hosts_load_table.get_string()
    if rpt_format == 'html':
        check_result_detail = hosts_load_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    host_load_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, host_load_check_output)   

def segments_check(rpt_format):
    check_item = 'Segment Status'
    check_result = 'OK'
    check_result_detail = ''
    gpstate_cmd = 'gpstate -e || true'
    gpstate_output = _execute_shell_command(gpstate_cmd)
    if 'mirroring is not configured' in gpstate_output:
        check_result = 'NOT OK'
        check_result_detail = 'Physical mirroring is not configured'
    else:
        gpstate_output_list = [line.split(':')[-1] for line in gpstate_output.splitlines()]
        gpstate_output_start_line =  gpstate_output_list.index('-Segment Mirroring Status Report')
        check_result_detail = '\n'.join(gpstate_output_list[gpstate_output_start_line-1:])
        if rpt_format == 'html':
            check_result_detail = '<br>'.join(gpstate_output_list[gpstate_output_start_line-1:])
        if 'All segments are running normally' not in check_result_detail:
            check_result = 'NOT OK'
    gpstate_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, gpstate_check_output)

def standby_check(dbconn, pg_version, rpt_format):
    check_item = 'Standby Master'
    check_result = 'OK'
    check_result_detail = ''
    if pg_version == 'cbdb':
        cursor = execSQL(dbconn, check_standby_sql_pg9)
    if pg_version == 'legacy2':
        cursor = execSQL(dbconn, check_standby_sql_pg8)
    standby_output = cursor.fetchone()
    column_names_list = [row[0] for row in cursor.description]
    check_result_table = PrettyTable(column_names_list)
    if cursor.rowcount == 1:
        check_result_table.add_row(standby_output)
        if standby_output[1] != 'streaming':
            check_result = 'NOT OK'
    else:
        check_result = 'NOT OK' 
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    standby_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item,check_result,standby_check_output)

def guc_check(dbconn,rpt_format):
    check_item = 'Database Parameters'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn,get_guc_sql)
    get_guc_result = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    check_result_table = PrettyTable(column_names_list)
    for row in get_guc_result:
        check_result_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    guc_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, guc_check_output)

def db_size_check(db_list, rpt_format):
    check_item = 'Database Size'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        create_mpp_table_size_view = execSQL(dbconn,create_mpp_table_size_view_sql)
        cursor = execSQL(dbconn,get_db_size_sql)
        db_size_result = cursor.fetchone()
        column_names_list = [row[0] for row in cursor.description]
        check_result_table = PrettyTable(column_names_list)
        check_result_table.add_row(db_size_result)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + check_result_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    db_size_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, db_size_output)

def schema_size_check(db_list,rpt_format):
    check_item = 'Schema Size'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        create_mpp_table_size_view = execSQL(dbconn,create_mpp_table_size_view_sql)
        cursor = execSQL(dbconn,get_schema_size_sql)
        schema_size_result = cursor.fetchall()
        column_names_list = [row[0] for row in cursor.description]
        check_result_table = PrettyTable(column_names_list)
        for row in schema_size_result:
            check_result_table.add_row(row)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + check_result_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    schema_size_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, schema_size_output)

def table_size_check(db_list,rpt_format):
    check_item = 'Tables Size'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        create_mpp_table_size_view = execSQL(dbconn,create_mpp_table_size_view_sql)
        cursor = execSQL(dbconn,get_table_size_sql)
        table_size_result = cursor.fetchall()
        column_names_list = [row[0] for row in cursor.description]
        check_result_table = PrettyTable(column_names_list)
        for row in table_size_result:
            check_result_table.add_row(row)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + check_result_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    table_size_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, table_size_output)

def data_skew_check(pg_version,db_list,rpt_format):
    check_item = 'Tables Data Skew'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        if pg_version == 'legacy2':
            create_function_output = execSQL(dbconn,create_data_skew_fn_sql)
            cursor = execSQL(dbconn,get_data_skew_sql)
            get_data_skew_result = cursor.fetchall()
            column_names_list = [row[0] for row in cursor.description]
            check_result_table = PrettyTable(column_names_list)
            if cursor.rowcount >= 1:
                check_result = 'NOT OK'
                for row in get_data_skew_result:
                    check_result_table.add_row(row)
        elif pg_version == 'cbdb':
            check_result_table = PrettyTable(['schema','table','storage','skew_metric','value'])
            # AO tables: skew by on-disk segment file size (old, fastest method)
            cursor = execSQL(dbconn, get_db_oid_sql)
            db_oid = cursor.fetchone()[0]
            execSQL(dbconn, 'DROP EXTERNAL TABLE IF EXISTS public.db_files_ext')
            execSQL(dbconn, create_db_files_ext_sql.format(db_oid))
            cursor = execSQL(dbconn, get_ao_size_skew_sql)
            for row in cursor.fetchall():
                check_result = 'NOT OK'
                check_result_table.add_row([row[0], row[1], row[2], 'seg_size_gap%', row[3]])
            execSQL(dbconn, 'DROP EXTERNAL TABLE IF EXISTS public.db_files_ext')
            # PAX tables: server-side skew coefficient, called per table to avoid DSM slot exhaustion
            cursor = execSQL(dbconn, get_pax_table_list_sql)
            pax_table_list = cursor.fetchall()
            for schema_name, table_name, table_oid in pax_table_list:
                cursor = execSQL(dbconn, get_skew_coefficient_sql, (table_oid,))
                skew_row = cursor.fetchone()
                if skew_row is None or skew_row[0] is None:
                    continue
                skew_coeff = round(skew_row[0], 2)
                # skccoeff is the coefficient of variation (stddev/avg) of per-segment
                # row counts, on a percentage scale. It is a different metric from the
                # max-min gap used for AO tables, so it has its own threshold aligned
                # with Greenplum's guidance (>10% skew -> re-evaluate distribution).
                if skew_coeff > TABLE_SKEW_CV_PERCENT:
                    check_result = 'NOT OK'
                    check_result_table.add_row([schema_name, table_name, 'pax', 'skew_coeff%', skew_coeff])
            check_result_table.sortby = "value"
            check_result_table.reversesort = True
        elif pg_version == 'legacy3':
            cursor = execSQL(dbconn,get_ao_table_list_sql)
            table_list = cursor.fetchall()
            if len(table_list) == 0:
                continue
            check_result_table = PrettyTable(['schema','table','min_count','max_count','sum_count','skew_percent'])
            for table in table_list:
                schema_name = table[0]
                table_name = table[1]
                ao_seg_name = table[2]
                cursor = execSQL(dbconn, get_ao_data_skew_sql, (ao_seg_name,))
                skew_result = cursor.fetchone()
                if None in skew_result:
                    continue
                seg_count = skew_result[0]
                min_count = int(skew_result[1])
                max_count = int(skew_result[2])
                sum_count = skew_result[3]
                avg_count = sum_count/(seg_count+1)
                skew_percent = (max_count/avg_count - 1) * 100
                if sum_count > 64 and skew_percent > TABLE_SKEW_PERCENT:
                    check_result = 'NOT OK.'
                    check_result_table.add_row([schema_name,table_name,min_count,max_count,sum_count,skew_percent])
            check_result_table.sortby = "skew_percent"
            check_result_table.reversesort = True
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + check_result_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div   style="clear:both">\n' + check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    data_skew_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, data_skew_output)

def resqueue_check(dbconn,rpt_format):
    check_item = 'Resource Queues Setting'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn,get_resqueue_sql)
    resqueues = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    check_result_table = PrettyTable(column_names_list)
    for row in resqueues:
        check_result_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    if cursor.rowcount == 1:
        check_result = 'NOT OK'
    resqueues_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, resqueues_check_output)

def resgroup_check(dbconn,resource_manager,rpt_format):
    check_item = 'Resource Groups Setting'
    check_result = 'OK'
    check_result_detail = ''
    builtin_groups = ['default_group', 'admin_group', 'system_group']
    cursor = execSQL(dbconn,get_resgroup_sql)
    resgroups = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    groupname_idx = column_names_list.index('groupname')
    check_result_table = PrettyTable(column_names_list)
    for row in resgroups:
        check_result_table.add_row(row)
    custom_groups = [row[groupname_idx] for row in resgroups if row[groupname_idx] not in builtin_groups]
    if rpt_format == 'text':
        check_result_detail = 'Resource manager mode: ' + resource_manager + '\n\n' + check_result_table.get_string()
    if rpt_format == 'html':
        check_result_detail = 'Resource manager mode: ' + resource_manager + '<br><br>' + check_result_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    if resource_manager in ('group', 'group-v2') and len(custom_groups) == 0:
        check_result = 'NOT OK'
    resgroup_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, resgroup_check_output)

def pg_activity_check(dbconn, pg_version, rpt_format):
    check_item = 'Current Long Running(> 1hr) Queries'
    check_result = 'OK'
    check_result_detail = ''
    if pg_version == 'cbdb':
        cursor = execSQL(dbconn, get_pg_activity_sql_pg14)
    if pg_version == 'legacy3':
        cursor = execSQL(dbconn, get_pg_activity_sql_pg9)
    if pg_version == 'legacy2':
        cursor = execSQL(dbconn, get_pg_activity_sql_pg8)
    pg_activity_result = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    pg_activity_table = PrettyTable(column_names_list)
    if cursor.rowcount > 0:
        check_result = 'NOT OK'
        for row in pg_activity_result:
            pg_activity_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = pg_activity_table.get_string()
    if rpt_format == 'html':
        check_result_detail = pg_activity_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    pg_activity_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, pg_activity_check_output)

def pg_locks_check(dbconn, pg_version, rpt_format):
    check_item = 'Current Database Locks'
    check_result = 'OK'
    check_result_detail = ''
    if pg_version == 'legacy3' or pg_version == 'cbdb':
        cursor = execSQL(dbconn, get_pg_locks_sql_pg9)
    if pg_version == 'legacy2':
        cursor = execSQL(dbconn, get_pg_locks_sql_pg8)
    pg_locks_result = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    pg_locks_table = PrettyTable(column_names_list)
    if cursor.rowcount > 0:
        check_result = 'NOT OK'
        for row in pg_locks_result:
            pg_locks_table.add_row(row)
    if rpt_format == 'text': 
        check_result_detail = pg_locks_table.get_string()
    if rpt_format == 'html':
        check_result_detail = pg_locks_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    pg_locks_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, pg_locks_check_output)

def heap_table_bloat_check(db_list, rpt_format):
    check_item = 'Significant Bloat Heap Tables'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        cursor = execSQL(dbconn, get_heap_bloat_sql)
        bloat_result = cursor.fetchall()
        column_names_list = [row[0] for row in cursor.description]
        bloat_table = PrettyTable(column_names_list)
        if cursor.rowcount > 0:
            check_result = 'NOT OK'
            for row in bloat_result:
                bloat_table.add_row(row)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + bloat_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + bloat_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    bloat_table_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, bloat_table_check_output)

def ao_table_bloat_check(pg_version, db_list, rpt_format):
    check_item = 'Significant Bloat AO Tables'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        if pg_version == 'legacy2' or pg_version == 'cbdb':
            cursor = execSQL(dbconn, get_legacy2_ao_bloat_sql)
            bloat_result = cursor.fetchall()
            column_names_list = [row[0] for row in cursor.description]
            bloat_table = PrettyTable(column_names_list)
            if cursor.rowcount > 0:
                check_result = 'NOT OK'
                for row in bloat_result:
                    bloat_table.add_row(row)
        if pg_version == 'legacy3':
            cursor = execSQL(dbconn,get_ao_table_list_sql)
            table_list = cursor.fetchall()
            if len(table_list) == 0:
                continue
            bloat_table = PrettyTable(['schema','table','update_count'])
            for table in table_list:
                schema_name = table[0]
                table_name = table[1]
                ao_seg_name = table[2].replace('\'', '')
                get_bloat_sql = get_legacy3_ao_bloat_sql_base + ao_seg_name
                cursor = execSQL(dbconn, get_bloat_sql)
                bloat_result = cursor.fetchone()
                if None in bloat_result:
                    continue
                update_count = bloat_result[0]
                if update_count > TABLE_UPDATE_COUNT_3X:
                    check_result = 'NOT OK'
                    bloat_table.add_row([schema_name,table_name,update_count])
            bloat_table.sortby = "update_count"
            bloat_table.reversesort = True
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + bloat_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + bloat_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    bloat_table_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, bloat_table_check_output)

def db_age_check(dbconn, rpt_format):
    check_item = 'Database Age'
    check_result = 'OK'
    check_result_detail = ''
    cursor = execSQL(dbconn, get_db_age_sql)
    db_age_result = cursor.fetchall()
    column_names_list = [row[0] for row in cursor.description]
    db_age_table = PrettyTable(column_names_list)
    for row in db_age_result:
        db_age_table.add_row(row)
        if row[-1] != 'BELOW WARN LIMIT':
            check_result = 'NOT OK'
    if rpt_format == 'text': 
        check_result_detail = db_age_table.get_string()
    if rpt_format == 'html':
        check_result_detail = db_age_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
    db_age_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, db_age_check_output)

def temp_schema_check(db_list,rpt_format):
    check_item = 'Temp Schema'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        cursor = execSQL(dbconn, get_temp_schema_sql)
        temp_schema_result = cursor.fetchall()
        column_names_list = [row[0] for row in cursor.description]
        temp_schema_table = PrettyTable(column_names_list)
        if cursor.rowcount > 0:
            check_result = 'NOT OK'
            for row in temp_schema_result:
                temp_schema_table.add_row(row)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + temp_schema_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + temp_schema_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    temp_schema_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, temp_schema_check_output)

def stale_stats_check(db_list,rpt_format):
    check_item = 'Tables Statistics'
    check_result = 'OK'
    check_result_detail = ''
    for db in db_list:
        dbconn = pgdb.connect(database=db, host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
        cursor = execSQL(dbconn, get_stale_stats_sql)
        stale_stats_result = cursor.fetchall()
        column_names_list = [row[0] for row in cursor.description]
        stale_stats_table = PrettyTable(column_names_list)
        if cursor.rowcount > 0:
            check_result = 'NOT OK'
            for row in stale_stats_result:
                stale_stats_table.add_row(row)
        if rpt_format == 'text': 
            check_result_detail += '\nDatabase: ' + db + '\n' + stale_stats_table.get_string() + '\n'
        if rpt_format == 'html':
            check_result_detail += '<div style="clear:both"><br><b><li>Database: ' + db + '</li></b><div style="clear:both">\n' + stale_stats_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        }) + '\n<br>'
        dbconn.close()
    stale_stats_check_output = check_items_output(check_item, check_result, check_result_detail, rpt_format)
    return (check_item, check_result, stale_stats_check_output)

##################  Main function ################## 
def synxdb_health_check(configs):
    #### Connect DB and get hosts list in cluster
    rpt_format = configs['report_format']
    dbconn = pgdb.connect(database='postgres', host='{0}:{1}'.format(MASTER_HOST_NAME,MASTER_PORT), user='gpadmin')
    hosts_list = get_hosts_list(dbconn)
    db_list = get_db_list(dbconn)  
    pg_version = get_pg_version(dbconn)
    create_mpp_table_size_view = execSQL(dbconn,create_mpp_table_size_view_sql)

    #### Start checks
    report_output_list = []
    if configs['db_version_check']['enabled']:
        print('Checking database version...')
        get_db_version_output = get_db_version(dbconn,rpt_format)
        report_output_list.append(get_db_version_output)
        print('Done')
    if configs['seg_config_check']['enabled']:
        print('Checking segment configuration...')
        seg_config_check_output = seg_config_check(dbconn,rpt_format)
        report_output_list.append(seg_config_check_output)
        print('Done')
    if configs['os_version_check']['enabled']:
        print('Check OS version...')
        os_version_check_output = os_version_check(hosts_list,rpt_format)
        report_output_list.append(os_version_check_output)
        print('Done')
    if configs['cpu_cores_check']['enabled']:
        print('Checking CPU cores...')
        cpu_cores_check_output = cpu_cores_check(hosts_list,rpt_format)
        report_output_list.append(cpu_cores_check_output)
        print('Done')
    if configs['memory_size_check']['enabled']:
        print('Checking physical memory size...')
        memory_size_check_output = memory_size_check(hosts_list,rpt_format)
        report_output_list.append(memory_size_check_output)
        print('Done')
    if configs['diskspace_check']['enabled']:
        print('Checking local diskspace...')
        diskspace_check_output = diskspace_check(dbconn,rpt_format)
        report_output_list.append(diskspace_check_output)
        print('Done')
    if configs['host_load_check']['enabled']:
        print('Checking host load...')
        host_load_check_output = host_load_check(hosts_list,rpt_format)
        report_output_list.append(host_load_check_output)
        print('Done')
    if configs['segments_status_check']['enabled'] and pg_version != 'legacy3':
        print('Checking segment status...')
        segments_check_output = segments_check(rpt_format)
        report_output_list.append(segments_check_output)
        print('Done')
    if configs['standby_status_check']['enabled'] and pg_version != 'legacy3':
        print('Checking standby master status...')
        standby_check_output = standby_check(dbconn, pg_version,rpt_format)
        report_output_list.append(standby_check_output)
        print('Done')
    if configs['guc_check']['enabled']:
        print('Checking GUCs...')
        guc_check_output = guc_check(dbconn,rpt_format)
        report_output_list.append(guc_check_output)
        print('Done')
    # Resource management: for CBDB/SynxDB pick the active mechanism based on
    # gp_resource_manager. In group/group-v2 mode only the resource group check
    # is relevant; in queue mode only the resource queue check is. Legacy 2x/3x
    # have no resource groups, so they always use the resource queue check.
    resource_manager = ''
    if pg_version == 'cbdb':
        resource_manager = get_resource_manager_mode(dbconn)
    if pg_version == 'cbdb' and resource_manager in ('group', 'group-v2'):
        if configs['resgroup_check']['enabled']:
            print('Checking resource group settings...')
            resgroup_check_output = resgroup_check(dbconn, resource_manager, rpt_format)
            report_output_list.append(resgroup_check_output)
            print('Done')
    else:
        if configs['res_queue_check']['enabled']:
            print('Checking resource queue settings...')
            resqueue_check_output = resqueue_check(dbconn,rpt_format)
            report_output_list.append(resqueue_check_output)
            print('Done')
    if configs['pg_activity_check']['enabled']:
        print('Checking current long running queries...')
        pg_activity_check_output = pg_activity_check(dbconn, pg_version,rpt_format)
        report_output_list.append(pg_activity_check_output)
        print('Done')
    if configs['pg_locks_check']['enabled']:
        print('Checking current locks...')
        pg_locks_check_output = pg_locks_check(dbconn, pg_version,rpt_format)
        report_output_list.append(pg_locks_check_output)
        print('Done')
    if configs['db_size_check']['enabled']:
        print('Checking databases size...')
        db_size_check_output = db_size_check(db_list,rpt_format)
        report_output_list.append(db_size_check_output)
        print('Done')
    if configs['schema_size_check']['enabled']:
        print('Checking schemas size...')
        schema_size_check_output = schema_size_check(db_list,rpt_format)
        report_output_list.append(schema_size_check_output)
        print('Done')
    if configs['table_size_check']['enabled']:
        print('Checking tables size...')
        table_size_check_output = table_size_check(db_list,rpt_format)
        report_output_list.append(table_size_check_output)
        print('Done')
    if configs['heap_table_bloat_check']['enabled'] and pg_version != 'legacy3':
        print('Checking bloated heap tables...')
        table_bloat_check_output = heap_table_bloat_check(db_list,rpt_format)
        report_output_list.append(table_bloat_check_output)
        print('Done')
    if configs['ao_table_bloat_check']['enabled']:
        print('Checking bloated AO tables...')
        table_bloat_check_output = ao_table_bloat_check(pg_version,db_list,rpt_format)
        report_output_list.append(table_bloat_check_output)
        print('Done')
    if configs['data_skew_check']['enabled']:
        print('Checking skewed tables...')
        data_skew_check_output = data_skew_check(pg_version,db_list,rpt_format)
        report_output_list.append(data_skew_check_output)
        print('Done')
    if configs['stale_stats_check']['enabled']:
        print('Checking tables without up-to-date statistics...')
        stale_stats_check_output = stale_stats_check(db_list,rpt_format)
        report_output_list.append(stale_stats_check_output)
        print('Done')
    if configs['db_age_check']['enabled'] and pg_version != 'legacy3':
        print('Checking databases age...')
        db_age_check_output = db_age_check(dbconn,rpt_format)
        report_output_list.append(db_age_check_output)
        print('Done')
#    if configs['table_age_check']['enabled'] and pg_version != 'legacy3':
#        print('Checking tables age...')
#        table_age_check_output = table_age_check(db_list,rpt_format)
#        report_output_list.append(table_age_check_output)
#        print('Done')
    if configs['temp_schema_check']['enabled']:
        print('Checking orphan temp scehmas...')
        temp_schema_check_output = temp_schema_check(db_list,rpt_format)
        report_output_list.append(temp_schema_check_output)
        print('Done')
#    if configs['master_log_check']['enabled']:
#        master_log_check_output = master_log_check(dbconn,rpt_format)
#        report_output_list.append(master_log_check_output)
    dbconn.close()

    #### Construct Report
    report_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    if rpt_format == 'text':
        report_header = (
            '# SynxDB Health Check Report\n'
            'Report Date: %s\n\n'
        ) % (report_time)
        check_summary_output = '## Database Check Summary\n'
        check_items_output='\n\n## Database Health Check Details\n'
        report_end = '\n'
    if rpt_format == 'html':
        report_header = """
            <html>
                <head>
                    <title>
                        SynxDB Health Check Report
                    </title>
                </head>
                <body>
                    <H1>SynxDB Health Check Report</H1>
                    <p><b>Report Date:<b> %s</p>
        """ % (report_time)
        check_summary_output = '<h2>Database Check Summary</h2>'
        check_items_output='''
            <div style="clear:both"><br><h2>Database Health Check Details</h2>
        '''
        report_end = """
                </body>
            </html>
        """

    check_summary_table = PrettyTable(["No.","Check Item","Check Result"])
    green_print_flag = '\033[1;32m'
    red_print_flag = '\033[1;31m'
    color_print_end_flag = '\033[0m'
    color_flag = ''
    for idx, item in enumerate(report_output_list):
        check_item = item[0]
        check_result = item[1]
        check_details = item[2]
        if rpt_format == 'text':
            if check_result == 'OK':
                color_flag = green_print_flag
            if check_result == 'NOT OK':
                color_flag = red_print_flag
            check_summary_table.add_row([color_flag+str(idx+1)+color_print_end_flag, color_flag+check_item+color_print_end_flag, color_flag+check_result+color_print_end_flag])
        if rpt_format == 'html':
            check_summary_table.add_row([idx+1,check_item,check_result])
        check_items_output += check_details
    if rpt_format == 'text':
        check_summary_output += check_summary_table.get_string()
    if rpt_format == 'html':
        check_summary_table_html = check_summary_table.get_html_string(attributes={
            'width': '60%',
            'align': 'left',
            'BORDERCOLOR': '#330000',
            'border': '2',
        })
        check_summary_table_html = re.sub('<td>%s</td>'%('NOT OK'), '<td bgcolor="%s">%s</td>'%('yellow', 'NOT OK'), check_summary_table_html)
        check_summary_output += check_summary_table_html
    report_output = report_header + check_summary_output + check_items_output + report_end
    
    #### Output report to file
    report_path = configs['report_path']
    if not os.path.exists(report_path):
        os.mkdir(report_path)
    report_suffix = '.rpt'
    if rpt_format == 'html':
        report_suffix = '.html'
    report_file = report_path + '/synxdb-health-check-' + time.strftime("%Y-%m-%d", time.localtime()) + report_suffix
    # Strip ANSI color codes only. The pattern must be anchored to the escape
    # sequence ([0-9;]*m); a greedy '.*m' would match from the first escape to
    # the last 'm' on a line and delete the cell text and column separators in
    # between, collapsing colored summary rows to empty cells.
    report_output_without_color_flag  = re.sub(r'\033\[[0-9;]*m','',report_output)
    f = codecs.open(report_file, 'w', 'utf-8')
    f.write(report_output_without_color_flag)
    f.close()
    if rpt_format == 'text':
        print(report_output)
    print('Health check report has been saved in %s' % report_file)

def main():
    parser = argparse.ArgumentParser(description='Run health check as defined in a YAML formatted control file.')
    parser.add_argument("-f", "--config-file", type=argparse.FileType('r'), metavar="<filename>", dest="file", help='A YAML file that contains the health check items setting.')
    args = parser.parse_args()
    if not args.file:
        parser.print_usage()
        return sys.exit(1)
    with args.file as f:
        try:
            configs = yaml.safe_load(f.read())
        except Exception as e:
            print(args.file.name + ' is not a valid YAML config file.\n')
            parser.print_usage()
            return sys.exit(1)
    synxdb_health_check(configs)
     
if __name__ == "__main__":
    main()
