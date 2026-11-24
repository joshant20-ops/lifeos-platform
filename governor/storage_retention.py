"""LifeOS retention policy/assessment and separately gated exact-file executor.

No scheduler, backup implementation, GitHub command execution or enabled delete
entrypoint. Runtime guards must be supplied by an installed reviewed Governor
adapter. Existing evidence without producer timestamps remains HOLD.
"""
import argparse
import collections
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import time

UTC = dt.timezone.utc
MAX_INPUT = 16 * 1024**2
MAX_RECORDS = 10000
MAX_FILES = 10000
FILE_CATEGORIES = {'automation_backup', 'repair_snapshot', 'successful_job', 'failed_job', 'diagnostic', 'cron_log', 'database_backup'}
CATEGORIES = FILE_CATEGORIES | {'predbat_image','paperless_rehearsal'}
STAT_FIELDS = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
STATE_ROOT = pathlib.Path('/var/lib/lifeos-storage-audit/retention')


def stamp(value):
    t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None: raise ValueError('utc_timestamp_required')
    return t.astimezone(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def producer_admission(service, job_id, source_epoch_sha256, estimate, existing, capacity, policy, now):
    """Thin guard for existing backup creators, not another backup system.

    A refused required pre-change backup must also stop the proposed change.
    Reuse is permitted only for the same job AND unchanged source epoch.
    """
    if not isinstance(job_id,str) or not job_id or not isinstance(source_epoch_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',source_epoch_sha256):return 'BLOCK_INVALID_IDENTITY'
    if type(estimate) is not int or estimate<0:return 'BLOCK_SIZE_ESTIMATE_REQUIRED'
    if (not all(type(capacity.get(k)) is int and capacity[k]>=0 for k in ('available_bytes','reserve_bytes','capacity_bytes'))
            or capacity['reserve_bytes']<(capacity['capacity_bytes']*policy['minimum_free_percent']+99)//100):return 'BLOCK_CAPACITY_EVIDENCE_REQUIRED'
    if estimate>capacity['available_bytes']-capacity['reserve_bytes']:return 'BLOCK_PROTECTED_RESERVE'
    limits=dict(policy['producer_limits']);limits.update(policy.get('services',{}).get(service,{}).get('producer_limits',{}))
    if (type(limits['max_daily_generations']) is not int or limits['max_daily_generations']<1
            or type(limits['min_interval_seconds']) is not int or limits['min_interval_seconds']<0
            or (limits['max_daily_bytes'] is not None and (type(limits['max_daily_bytes']) is not int or limits['max_daily_bytes']<0))):return 'BLOCK_INVALID_PRODUCER_POLICY'
    rows=[g for g in existing if g.get('service')==service]
    if any(g.get('active') is not False for g in rows):return 'BLOCK_ACTIVE_OR_UNKNOWN_PRODUCER'
    for g in rows:
        if g.get('job_id')==job_id and g.get('source_epoch_sha256')==source_epoch_sha256:
            return 'REUSE_VERIFIED_GENERATION' if g.get('state')=='completed' and g.get('verification')=='passed' else 'BLOCK_EXISTING_ATTEMPT'
    try:
        recent=[g for g in rows if stamp(g['created_at']).date()==now.date()]
        if len(recent)>=limits['max_daily_generations']:return 'BLOCK_DAILY_GENERATION_LIMIT'
        if rows and (now-max(stamp(g['created_at']) for g in rows)).total_seconds()<limits['min_interval_seconds']:return 'BLOCK_CREATION_COOLDOWN'
        if limits['max_daily_bytes'] is not None and sum(g['allocated_bytes'] for g in recent)+estimate>limits['max_daily_bytes']:return 'BLOCK_DAILY_BYTE_LIMIT'
    except (KeyError,TypeError,ValueError):return 'BLOCK_UNVERIFIED_PRODUCER_STATE'
    return 'ALLOW_REGISTERED_PRODUCER'


def policy_rules(policy, service, category):
    if policy.get('schema_version') != 1 or policy.get('minimum_free_percent', 0) < 10:
        raise ValueError('invalid_policy')
    if set(policy['categories'])!=CATEGORIES:raise ValueError('unknown_category')
    rule = dict(policy['categories'][category])
    rule.update(policy.get('services', {}).get(service, {}).get(category, {}))
    days = rule['days']
    if days is not None and (type(days) is not int or not 0 <= days <= 3650): raise ValueError('invalid_retention')
    if type(rule['recovery_required']) is not bool or type(rule['offhost_required']) is not bool: raise ValueError('invalid_policy')
    if type(rule.get('max_backup_age_hours',48)) is not int or not 1<=rule.get('max_backup_age_hours',48)<=8760:raise ValueError('invalid_freshness_policy')
    return rule


def safe_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value: raise ValueError('invalid_relative_path')
    parts = value.split('/')
    if any(p in {'', '.', '..'} for p in parts): raise ValueError('invalid_relative_path')
    return parts


def point_ok(point):
    return point.get('verified') is True and point.get('available') is True and point.get('protected') is True


def reasons(g, inventory, policy, now):
    why = []
    try:
        if not all(isinstance(g[k], str) and g[k] for k in ('service', 'generation_id', 'category', 'root_id')): raise ValueError()
        rule = policy_rules(policy, g['service'], g['category'])
        created, completed = stamp(g['created_at']), stamp(g['completed_at'])
        if not created <= completed <= now or g['timestamp_verified'] is not True or not g['producer_evidence_id']:
            why.append('unverified_timestamp')
        if inventory.get('complete') is not True: why.append('inventory_incomplete')
        observed = stamp(inventory['observed_at'])
        if not 0 <= (now-observed).total_seconds() <= policy['manifest_ttl_seconds']: why.append('stale_inventory')
        terminal={'completed','closed','verified'} | ({'failed'} if g['category'] in {'failed_job','diagnostic'} else set())
        if g['state'] not in terminal or g['active'] is not False: why.append('active_or_nonterminal')
        if g['references_verified'] is not True or g['dependencies'] or g['open_references'] != 0 or g['holds']:
            why.append('reference_or_hold')
        if g['verification'] != 'passed': why.append('unverified_generation')
        if type(g['offhost_required']) is not bool:raise ValueError()
        if type(g['logical_bytes']) is not int or type(g['allocated_bytes']) is not int or min(g['logical_bytes'],g['allocated_bytes']) < 0: raise ValueError()
        if g.get('live_data') is not False or g.get('database_volume') is not False: why.append('protected_live_data')
        points = [p for p in inventory['recovery_points'] if p.get('service') == g['service'] and point_ok(p)]
        if any(p.get('generation_id') == g['generation_id'] for p in points): why.append('protected_recovery_point')
        others = [p for p in points if p.get('generation_id') != g['generation_id']]
        if (rule['recovery_required'] or g['category'] in {'automation_backup','database_backup','repair_snapshot'}) and not others: why.append('no_retained_verified_recovery')
        if (rule['offhost_required'] or g.get('offhost_required') is True) and not any(p.get('offhost') is True and p.get('independent_failure_domain') is True for p in others):
            why.append('offhost_coverage_unproven')
        category = g['category']
        if category == 'predbat_image':
            identity = g['image_id']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', identity): why.append('invalid_image_id')
            protected = inventory['protected_images'].get(g['service'], {})
            required = {'production', 'rollback', 'approved_history_1', 'approved_history_2'}
            if set(protected) != required or len(set(protected.values()))!=4 or any(not re.fullmatch(r'sha256:[a-f0-9]{64}',p) for p in protected.values()): why.append('image_holds_unverified')
            if identity in protected.values() or identity in inventory['container_image_ids']: why.append('protected_image')
            if g['image_references_verified'] is not True or g['tags'] or g['registry_digests']: why.append('image_reference_hold')
        else:
            safe_relative(g['relative_path'])
            if category in FILE_CATEGORIES:
                files=g['files']
                if not isinstance(files,list) or not 0<len(files)<=MAX_FILES: raise ValueError()
                seen=set()
                for f in files:
                    relative=f['relative_path'];safe_relative(relative)
                    if not relative.startswith(g['relative_path'].rstrip('/')+'/') or relative in seen: raise ValueError()
                    seen.add(relative)
                    if set(f['identity'])!=set(STAT_FIELDS) or not all(type(v) is int and v>=0 for v in f['identity'].values()): raise ValueError()
                    if type(f['allocated_bytes']) is not int or f['allocated_bytes']<0: raise ValueError()
                if sum(f['identity']['st_size'] for f in files)!=g['logical_bytes'] or sum(f['allocated_bytes'] for f in files)!=g['allocated_bytes']: raise ValueError()
            base = stamp(g['closed_at']) if category == 'repair_snapshot' else completed
            if category=='repair_snapshot' and (g.get('closure_verified') is not True or not g.get('closure_evidence_id')):why.append('unverified_closure')
            if not completed <= base <= now: why.append('invalid_closure')
            floor = policy['record_minimum_days'][g['record_class']]
            days = max(rule['days'], floor)
            if not base < now-dt.timedelta(days=days): why.append('within_retention')
            if category == 'paperless_rehearsal':
                if g.get('temporary') is not True or g.get('restore_verification_passed') is not True: why.append('rehearsal_not_verified')
                why.append('existing_rehearsal_adapter_required')
    except (KeyError, ValueError, TypeError, AttributeError):
        why.append('missing_or_invalid_metadata')
    return sorted(set(why))


def assess(inventory, policy, now):
    if set(policy['categories'])!=CATEGORIES or type(policy['minimum_free_percent']) is not int or policy['minimum_free_percent']<10:raise ValueError('invalid_policy')
    if inventory.get('schema_version') != 1 or len(inventory['generations']) > MAX_RECORDS: raise ValueError('inventory_bounds')
    ids = [(g.get('service'),g.get('generation_id')) for g in inventory['generations']]
    if len(ids) != len(set(ids)): raise ValueError('duplicate_generation')
    held = collections.Counter(); selected = []; counts = collections.Counter(); sizes = collections.Counter()
    eligible_bytes = 0; eligible_count=0; unverified=0; backup_failures=0; backup_ages={}
    for g in inventory['generations']:
        category = g.get('category')
        why = reasons(g, inventory, policy, now)
        if category in CATEGORIES:
            counts[category] += 1
            if type(g.get('allocated_bytes')) is int and g['allocated_bytes'] >= 0: sizes[category] += g['allocated_bytes']
        if category in {'automation_backup','database_backup'} and (g.get('state')=='failed' or g.get('verification')=='failed'):backup_failures+=1
        if category in {'automation_backup','database_backup'}:
            key=(g.get('service'),category);backup_ages.setdefault(key,None)
            try:
                age=(now-stamp(g['completed_at'])).total_seconds()
                if g['timestamp_verified'] is True and g['verification']=='passed' and age>=0:
                    backup_ages[key]=age if backup_ages[key] is None else min(backup_ages[key],age)
            except (KeyError,ValueError,TypeError):pass
        if why:
            held.update(why)
            if set(why)&{'missing_or_invalid_metadata','unverified_timestamp','stale_inventory','inventory_incomplete','unverified_generation'}:unverified+=1
            continue
        eligible_count+=1
        eligible_bytes += g['allocated_bytes']
        operations=lambda item:1 if item['category']=='predbat_image' else len(item.get('files',[]))
        if ((not selected or g['root_id']==selected[0]['root_id']) and len(selected) < policy['max_batch_generations']
                and sum(operations(item) for item in selected)+operations(g)<=policy['max_batch_operations']
                and sum(r['allocated_bytes'] for r in selected)+g['allocated_bytes'] <= policy['max_batch_bytes']):
            selected.append(g)
    manifest = {'schema_version':1,'created_at':now.isoformat(),'policy_sha256':digest(policy),
                'inventory_sha256':digest(inventory),'root_id':selected[0]['root_id'] if selected else None,'entries':selected}
    freshness_violations=sum(1 for (service,category),age in backup_ages.items() if age is None or age>policy_rules(policy,service,category).get('max_backup_age_hours',48)*3600)
    if inventory.get('complete') is not True and not ids:held['inventory_incomplete']=1;unverified=1
    summary = {'schema_version':1,'status':'DRY_RUN' if inventory.get('complete') is True else 'INCOMPLETE','observed_at':now.isoformat(),'records':len(ids),'eligible_generations':eligible_count,
               'backup_freshness_violations':freshness_violations,
               'unverified_generations':unverified,'backup_failures':backup_failures,
               'potential_allocated_bytes':eligible_bytes,'guaranteed_recovered_bytes':0,
               'manifest_generations':len(selected),'held_reasons':dict(sorted(held.items())),
               'category_counts':dict(counts),'category_allocated_bytes':dict(sizes),
               'destructive_automation_enabled':False}
    return manifest, summary


def file_identity(info): return {k:getattr(info,k) for k in STAT_FIELDS}


def open_directory(path, start=None):
    if start is None and (not pathlib.Path(path).is_absolute() or '..' in pathlib.Path(path).parts):raise ValueError('absolute_registered_root_required')
    parts = safe_relative(path) if start is not None else pathlib.Path(path).parts
    fd = os.dup(start) if start is not None else os.open('/', os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in parts:
            if part == '/': continue
            next_fd = os.open(part, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = next_fd
        return fd
    except BaseException:
        os.close(fd); raise


@contextlib.contextmanager
def file_parent(root_fd, relative):
    parts = safe_relative(relative)
    fd = os.dup(root_fd) if len(parts)==1 else open_directory('/'.join(parts[:-1]),root_fd)
    try: yield fd, parts[-1]
    finally: os.close(fd)


def verify_file(root_fd, relative, expected):
    with file_parent(root_fd, relative) as (parent,name):
        fd = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != os.fstat(root_fd).st_dev:
                raise ValueError('unsafe_file_or_mount')
            if file_identity(info) != expected: raise ValueError('file_changed')
            return info
        finally: os.close(fd)


def private_info(info):return info.st_uid==0 and not info.st_mode&0o077


def trusted_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or not private_info(s) or s.st_size>MAX_INPUT: raise ValueError('unsafe_approval')
        return json.loads(f.read(MAX_INPUT+1))


class NativeDocker:
    """Fixed installed-native adapter, no prune, force or caller executables."""
    def run(self,args):
        image_id=lambda value:re.fullmatch(r'sha256:[a-f0-9]{64}',value) is not None
        allowed=(args in (['container','ls','--all','--quiet','--no-trunc'],['image','ls','--all','--quiet','--no-trunc'])
                 or (len(args)>=3 and args[:2]==['image','inspect'] and all(image_id(i) for i in args[2:]))
                 or (len(args)==3 and args[:2]==['image','rm'] and image_id(args[2]))
                 or (len(args)>=5 and args[:4]==['container','inspect','--format','{{.Image}}'] and all(re.fullmatch(r'[a-f0-9]{64}',i) for i in args[4:])))
        if not allowed:raise ValueError('native_operation_not_allowlisted')
        cp=subprocess.run(['/usr/bin/docker','--host','unix:///run/docker.sock',*args],capture_output=True,text=True,timeout=20,
                          env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        if cp.returncode or len(cp.stdout)>MAX_INPUT:raise ValueError('native_docker_unavailable')
        return cp.stdout
    def preflight(self,g,inventory):
        identity=g['image_id']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',identity):raise ValueError('invalid_image_id')
        image=json.loads(self.run(['image','inspect',identity]))[0]
        if image['Id']!=identity or image.get('RepoTags') or image.get('RepoDigests'):raise ValueError('image_changed')
        protected=inventory['protected_images'][g['service']].values()
        if identity in protected:raise ValueError('protected_image')
        pins=json.loads(self.run(['image','inspect',*sorted(protected)]))
        if {p['Id'] for p in pins}!=set(protected):raise ValueError('protected_images_unavailable')
        ids=self.run(['container','ls','--all','--quiet','--no-trunc']).split()
        if len(ids)>256 or any(not re.fullmatch(r'[a-f0-9]{64}',cid) for cid in ids):raise ValueError('container_bounds')
        refs=self.run(['container','inspect','--format','{{.Image}}',*ids]).split() if ids else []
        if identity in refs:raise ValueError('image_in_use')
    def remove(self,identity):
        self.run(['image','rm',identity])
        if identity in self.run(['image','ls','--all','--quiet','--no-trunc']).split():raise ValueError('image_removal_unverified')


def execute(manifest, policy, roots, state_dir, approval_path, guards, now, native=None):
    """Internal Governor adapter API, deliberately NOT exposed by the CLI.

    Guards are installed code, not request-supplied commands: global/producer
    locks, fresh complete lifecycle inventory, no open FDs, Tier0 health and
    off-host coverage must stay valid. Unavailable guards fail closed.
    """
    if policy.get('executor_enabled') is not True or os.geteuid()!=0: raise ValueError('executor_disabled')
    if manifest.get('schema_version')!=1:raise ValueError('manifest_schema')
    started=time.monotonic()
    h=digest(manifest); approval=trusted_json(approval_path)
    if (set(approval)!={'manifest_sha256','approved','expires_at'} or approval['approved'] is not True
            or approval['manifest_sha256']!=h or not now<stamp(approval['expires_at'])
            or not 0<=(now-stamp(manifest['created_at'])).total_seconds()<=policy['manifest_ttl_seconds']
            or manifest['policy_sha256']!=digest(policy)):
        raise ValueError('manifest_approval_invalid')
    remaining=min(policy['manifest_ttl_seconds']-(now-stamp(manifest['created_at'])).total_seconds(),(stamp(approval['expires_at'])-now).total_seconds())
    def still_authorised():
        if time.monotonic()-started>=remaining:raise ValueError('approval_expired')
    entries=manifest['entries']
    if sum(1 if g['category']=='predbat_image' else len(g.get('files',[])) for g in entries)>policy['max_batch_operations']:raise ValueError('operation_budget')
    if any(g['root_id']!=manifest['root_id'] for g in entries):raise ValueError('manifest_root_scope')
    if not entries or len(entries)>policy['max_batch_generations'] or sum(g['allocated_bytes'] for g in entries)>policy['max_batch_bytes']: raise ValueError('batch_bounds')
    if len({(g['service'],g['generation_id']) for g in entries})!=len(entries):raise ValueError('duplicate_generation')
    if not callable(getattr(guards,'exclusive',None)): raise ValueError('installed_guards_required')
    if not callable(getattr(guards,'approved_roots',None)) or roots!=guards.approved_roots():raise ValueError('unapproved_root_map')
    state=pathlib.Path(state_dir)
    if state!=STATE_ROOT:raise ValueError('unregistered_journal_directory')
    s=state.lstat()
    if not state.is_dir() or state.is_symlink() or not private_info(s): raise ValueError('unsafe_journal_directory')
    lock_fd=os.open(state/'retention.lock',os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    with os.fdopen(lock_fd,'a') as lock, guards.exclusive():
        ls=os.fstat(lock.fileno())
        if not stat.S_ISREG(ls.st_mode) or not private_info(ls):raise ValueError('unsafe_lock')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        journal=state/(h+'.journal.jsonl')
        fd=os.open(journal,os.O_RDWR|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as log:
            js=os.fstat(log.fileno())
            if not stat.S_ISREG(js.st_mode) or not private_info(js) or js.st_size>1024**2: raise ValueError('journal_bounds')
            prior=[json.loads(line) for line in log if line.strip()]
            prior=[r for r in prior if r['manifest_sha256']==h]
            if prior:
                if prior[-1]['event']=='complete': return {'status':'ALREADY_COMPLETE','net_available_delta_bytes':prior[-1]['net_available_delta_bytes']}
                raise ValueError('interrupted_cleanup_requires_reconciliation')
            def record(event,**extra):
                log.write(json.dumps({'manifest_sha256':h,'event':event,**extra},sort_keys=True)+'\n');log.flush();os.fsync(log.fileno())
            root_fds={}; prepared=[]; all_files=set()
            native=native or NativeDocker()
            try:
                guards.health()
                current=guards.inventory()
                if digest(current)!=manifest['inventory_sha256']: raise ValueError('inventory_changed')
                for g in entries:
                    if reasons(g,current,policy,now): raise ValueError('eligibility_changed')
                    if g not in current['generations']: raise ValueError('generation_not_in_inventory')
                    if g['category']=='predbat_image':
                        native.preflight(g,current);prepared.append(('image',g['image_id'],g,None));continue
                    if g['category'] not in FILE_CATEGORIES: raise ValueError('native_adapter_required')
                    if g['root_id'] not in roots: raise ValueError('unregistered_root')
                    if g['root_id'] not in root_fds:root_fds[g['root_id']]=open_directory(roots[g['root_id']])
                    rfd=root_fds[g['root_id']]
                    files=g['files']
                    if not files or len(files)>MAX_FILES: raise ValueError('file_bounds')
                    seen=set()
                    for f in files:
                        relative=f['relative_path']
                        if not relative.startswith(g['relative_path'].rstrip('/')+'/') or relative in seen: raise ValueError('file_scope')
                        key=(g['root_id'],relative)
                        if key in all_files:raise ValueError('duplicate_file')
                        all_files.add(key)
                        seen.add(relative);info=verify_file(rfd,relative,f['identity'])
                        if info.st_blocks*512!=f['allocated_bytes']:raise ValueError('allocation_changed')
                        guards.file_idle(rfd,relative)
                        prepared.append(('file',rfd,relative,f['identity']))
                before=guards.capacity()
                saved=state/(h+'.manifest.json')
                try:
                    mfd=os.open(saved,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                    with os.fdopen(mfd,'wb') as mf:mf.write(canonical(manifest));mf.flush();os.fsync(mf.fileno())
                except FileExistsError:
                    if digest(trusted_json(saved))!=h:raise ValueError('saved_manifest_changed')
                directory_fd=os.open(state,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                try:os.fsync(directory_fd)
                finally:os.close(directory_fd)
                record('begin',files=len(prepared))
                for index,(kind,rfd,relative,identity) in enumerate(prepared):
                    still_authorised()
                    guards.health();guards.revalidate()
                    if kind=='image':
                        latest=guards.inventory()
                        if reasons(relative,latest,policy,now):raise ValueError('image_eligibility_changed')
                        native.preflight(relative,latest);still_authorised();record('intent',index=index);still_authorised()
                        native.remove(rfd);record('removed',index=index);continue
                    verify_file(rfd,relative,identity);guards.file_idle(rfd,relative)
                    still_authorised()
                    record('intent',index=index)
                    with file_parent(rfd,relative) as (parent,name):
                        info=os.stat(name,dir_fd=parent,follow_symlinks=False)
                        if file_identity(info)!=identity: raise ValueError('file_changed')
                        still_authorised()
                        os.unlink(name,dir_fd=parent);os.fsync(parent)
                    record('removed',index=index)
                guards.health();after=guards.capacity()
                record('complete',net_available_delta_bytes=after-before)
                return {'status':'COMPLETE','net_available_delta_bytes':after-before}
            finally:
                for fd in root_fds.values():os.close(fd)


def metrics(summary, capacity, previous=None):
    values={'lifeos_retention_assessment_ok':1,'lifeos_retention_eligible_bytes':summary['potential_allocated_bytes'],
            'lifeos_retention_eligible_generations':summary['eligible_generations'],
            'lifeos_retention_guaranteed_recovered_bytes':0,'lifeos_retention_backup_failures':summary['backup_failures'],
            'lifeos_retention_backup_freshness_violations':summary['backup_freshness_violations'],
            'lifeos_retention_assessment_timestamp_seconds':int(stamp(summary['observed_at']).timestamp()),
            'lifeos_retention_unverified_generations':summary['unverified_generations'],
            'lifeos_storage_available_bytes':capacity['available_bytes'],
            'lifeos_storage_reserve_bytes':capacity['reserve_bytes']}
    if previous is not None: values['lifeos_storage_growth_bytes']=previous['available_bytes']-capacity['available_bytes']
    if not all(type(v) is int and -(2**60)<=v<=2**60 for v in values.values()):raise ValueError('invalid_metric')
    return ''.join(f'{k} {v}\n' for k,v in sorted(values.items()))


def weekly(history):
    """Aggregate existing daily summaries; no new weekly scheduler or raw paths."""
    if not history: return {'status':'NO_OBSERVATIONS','guaranteed_recovered_bytes':0}
    if len(history)>8: raise ValueError('weekly_window')
    ordered=sorted(history,key=lambda x:stamp(x['observed_at']))
    latest=stamp(ordered[-1]['observed_at'])
    ordered=[r for r in ordered if stamp(r['observed_at'])>=latest-dt.timedelta(days=7)]
    return {'status':'SUMMARY','observations':len(ordered),'net_storage_growth_bytes':ordered[0]['available_bytes']-ordered[-1]['available_bytes'],
            'latest_expired_generations':ordered[-1]['eligible_generations'],
            'latest_potential_allocated_bytes':ordered[-1]['potential_allocated_bytes'],'guaranteed_recovered_bytes':0}


def attention(summary,capacity):
    """Deterministic projection for the existing PA/HA Attention surface."""
    issues=[]
    if capacity['available_bytes']<capacity['reserve_bytes']:issues.append(('capacity','critical'))
    if summary['backup_failures'] or summary['backup_freshness_violations']:issues.append(('backup','high'))
    if summary['eligible_generations']:issues.append(('retention_backlog','normal'))
    if summary['unverified_generations']:issues.append(('metadata','normal'))
    return {'state':'attention' if issues else 'clear','attention_id':'storage-retention:'+issues[0][0] if issues else None,
            'kind':'storage_retention','count':len(issues),'severity':issues[0][1] if issues else 'normal',
            'summary':'Storage maintenance requires governed review' if issues else 'No storage maintenance exceptions',
            'source':'lifeos_storage_retention'}


def logrotate_entry(path, writer_reopen_verified=False):
    if not writer_reopen_verified or not re.fullmatch(r'/[A-Za-z0-9_./-]+',path) or any(p in {'.','..'} for p in path.split('/')):
        raise ValueError('log_writer_or_path_unverified')
    # Native rotation/compression only; archive expiration goes through manifests.
    return f'''"{path}" {{
    daily
    rotate -1
    missingok
    notifempty
    compress
    delaycompress
    nocopytruncate
    create 0600
    compresscmd /usr/bin/gzip
    compressoptions -1
}}
'''


def rotate_log(path, policy, guards):
    """Internal existing-Governor task adapter; never install in logrotate.d.

    The enclosing producer lease covers native rotation/compression, not merely
    a prerotate script. Native state prevents repeat daily rotation. No expiry
    or forced rotation is delegated to logrotate.
    """
    if policy.get('rotation_enabled') is not True or os.geteuid()!=0:raise ValueError('rotation_disabled')
    with guards.exclusive():
        guards.health();info=guards.log_metadata(path)
        if info.get('registered') is not True or info.get('open_references')!=0:raise ValueError('log_not_idle')
        content=logrotate_entry(path,info.get('writer_reopen_verified') is True)
        size=info['compression_input_bytes']
        if type(size) is not int or not 0<=size<=policy['compression_max_input_bytes']:raise ValueError('compression_budget')
        if guards.capacity()-info['reserve_bytes']<size*2:raise ValueError('compression_reserve')
        # State root is private, pre-installed by a separately approved adapter.
        s=STATE_ROOT.lstat()
        if STATE_ROOT.is_symlink() or not STATE_ROOT.is_dir() or not private_info(s):raise ValueError('unsafe_rotation_state')
        key=hashlib.sha256(content.encode()).hexdigest()
        cfg=STATE_ROOT/f'rotation-{key}.conf'
        try:
            fd=os.open(cfg,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as f:f.write(content);f.flush();os.fsync(f.fileno())
        except FileExistsError:
            existing=bounded_text(cfg)
            if existing!=content:raise ValueError('rotation_config_changed')
        cp=subprocess.run(['/usr/sbin/logrotate','--state',str(STATE_ROOT/f'rotation-{key}.state'),str(cfg)],
                          capture_output=True,timeout=30,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        if cp.returncode:raise ValueError('native_logrotate_failed')
        guards.health()
        return {'status':'NATIVE_LOGROTATE_RETURNED_SUCCESS','archive_deletion_authorised':False}


def bounded_text(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'r') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or not private_info(s) or s.st_size>4096:raise ValueError('unsafe_rotation_config')
        return f.read(4097)


def bounded_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_size>MAX_INPUT: raise ValueError('input_bounds')
        raw=f.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT: raise ValueError('input_bounds')
        return json.loads(raw)


def daily():
    """Optional hook in the existing observed-state daily exporter; no deletion."""
    config_path=os.environ.get('LIFEOS_RETENTION_CONFIG')
    if not config_path:return {'schema_version':1,'status':'NOT_CONFIGURED','guaranteed_recovered_bytes':0}
    try:
        c=bounded_json(config_path)
        if c.get('assessment_enabled') is not True:return {'schema_version':1,'status':'DISABLED','guaranteed_recovered_bytes':0}
        now=dt.datetime.now(UTC)
        _,summary=assess(bounded_json(c['inventory']),bounded_json(c['policy']),now)
        summary['observed_at']=now.isoformat()
        fs=os.statvfs(c['storage_root'])
        summary['available_bytes']=fs.f_bavail*fs.f_frsize
        summary['reserve_bytes']=(fs.f_blocks*fs.f_frsize+9)//10
        history=[]
        if c.get('history_root'):
            paths=[]
            with os.scandir(c['history_root']) as entries:
                for count,e in enumerate(entries):
                    if count>=4000:raise ValueError('history_bounds')
                    if re.fullmatch(r'[0-9]{8}T[0-9]{6}Z\.json',e.name) and e.is_file(follow_symlinks=False):paths.append(e.path)
            for path in sorted(paths,reverse=True)[:7]:
                previous=bounded_json(path).get('storage',{}).get('retention',{})
                if previous.get('status')=='DRY_RUN':history.append(previous)
        summary['weekly']=weekly(history+[summary])
        summary['attention']=attention(summary,summary)
        return summary
    except Exception:
        return {'schema_version':1,'status':'UNVERIFIED','guaranteed_recovered_bytes':0}


def main():
    parser=argparse.ArgumentParser(description='Read-only LifeOS retention assessment; no deletion CLI')
    parser.add_argument('inventory');parser.add_argument('--policy',required=True);parser.add_argument('--manifest')
    args=parser.parse_args()
    try:
        manifest,summary=assess(bounded_json(args.inventory),bounded_json(args.policy),dt.datetime.now(UTC))
        if args.manifest:
            fd=os.open(args.manifest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as f:json.dump(manifest,f,sort_keys=True);f.flush();os.fsync(f.fileno())
        print(json.dumps(summary,sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError):
        print('{"status":"UNVERIFIED","guaranteed_recovered_bytes":0}');raise SystemExit(2)


if __name__=='__main__':main()
