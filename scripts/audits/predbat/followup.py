#!/usr/bin/env python3
"""Pi-side follow-up. Reads existing evidence and targeted config descriptors.
Writes ONLY private evidence into its supplied job directory. No sudo/exec/pulls/
restart/prune/delete/config changes. Never authorises deletion automatically.
"""
import collections, datetime, hashlib, json, os, pathlib, re, stat, subprocess, sys, tarfile, time, zipfile

# Image identities/roles come only from the private local collector evidence.
PINS=set()
EXPECTED=set()
TRANSACTION_ROOT=None
STORAGE_ROOT=None
FOCUS_ID=None


def settings(d):
    global PINS, EXPECTED, TRANSACTION_ROOT, STORAGE_ROOT, FOCUS_ID
    rows=d.get('inventory',[])
    PINS={r.get('short_id') for r in rows if r.get('disposition')=='KEEP'}
    EXPECTED={r.get('short_id') for r in rows if r.get('disposition')=='HOLD'}
    TRANSACTION_ROOT=os.environ.get('PREDBAT_TRANSACTION_ROOT')
    STORAGE_ROOT=os.environ.get('PREDBAT_STORAGE_ROOT')
    FOCUS_ID=os.environ.get('PREDBAT_FOCUS_IMAGE_ID')
    if FOCUS_ID is not None and not re.fullmatch(r'[a-f0-9]{12}',FOCUS_ID):
        raise ValueError('invalid_focus_image_id')


def required_path(value,name):
    if not value or not pathlib.Path(value).is_absolute():
        raise ValueError('absolute_path_required:'+name)
    return value


def growth_targets(d):
    # Reuse previous allocated-byte baselines; never embed private measurements.
    targets=[]
    for item in d['growth']:
        root=item.get('path')
        if not isinstance(root,str) or not pathlib.Path(root).is_absolute(): continue
        baseline=None
        for line in (item.get('allocated_bytes_by_child') or '').splitlines():
            parts=line.split(None,1)
            if len(parts)==2 and parts[0].isdigit() and parts[1]==root:
                baseline=int(parts[0])
        targets.append((root,baseline))
    return targets[:3]

LIMIT=1024*1024
TEXT={'.py','.sh','.json','.yml','.yaml','.toml','.conf','.ini','.env','.md','.txt','.service','.timer'}
BINARY={'.png','.jpg','.jpeg','.gif','.ico','.webp','.woff','.woff2','.ttf','.otf','.so','.pyc','.mp4','.mp3','.pdf','.dump'}
ARCHIVES=('.tar','.tar.gz','.tgz','.zip','.gz','.bz2','.xz','.7z')
HEX=re.compile(r'(?<![0-9a-f])[0-9a-f]{12,64}(?![0-9a-f])',re.I)

def candidate_matches(text, rows):
    # Whole hexadecimal tokens, and version boundaries: v9.3.8 != v9.3.80.
    values=[x.lower() for x in HEX.findall(text)]
    hits=[]
    for r in rows:
        full=r['id'].removeprefix('sha256:').lower()
        kinds=[]
        if any(len(v)>=12 and full.startswith(v) for v in values): kinds.append('config_id')
        version=r.get('version')
        if version:
            bare=version.removeprefix('v')
            if re.search(r'(?<![\w.])v?'+re.escape(bare)+r'(?![\w.])',text,re.I): kinds.append('version_mention')
        for key in ('tags','registry_digests'):
            if any(v and v in text for v in r.get(key,[])): kinds.append(key)
        if kinds: hits.append({'short_id':r['short_id'],'kinds':kinds})
    return hits

def priority(path):
    p=pathlib.Path(path); s=str(p).lower(); name=p.name.lower()
    if p.suffix.lower() in BINARY: return 'irrelevant_binary'
    if re.search(r'/(node_modules|site-packages|__pycache__|static|fonts|assets)/',s): return 'unrelated_dependency_or_asset'
    if TRANSACTION_ROOT and pathlib.Path(path).is_relative_to(TRANSACTION_ROOT): return 'transaction_record'
    if name.endswith(ARCHIVES):
        return 'configuration_archive' if re.search(r'config|compose|deploy|rollback|manifest|backup',name) else 'opaque_archive_review'
    if re.search(r'/(media|originals|thumbnails)/',s): return 'unrelated_document_media'
    if name.startswith('.env') or re.search(r'compose|dockerfile|manifest|rollback|restore|recover|deploy|backup|index|catalog|fstab',name): return 'configuration_or_recovery_record'
    if '/scripts/' in s or '/usr/local/sbin/' in s or '/etc/lifeos/' in s: return 'executable_or_policy_record'
    return 'unresolved_nonobvious_file'

def category(path,text,matches):
    s=path.lower(); generic=bool(re.search(r'predbat|batpred',text,re.I))
    strong=any(any(k!='version_mention' for k in m['kinds']) for m in matches)
    related=generic or strong
    if not related: return 'ambiguous_version_only_reference' if matches else 'unrelated_reference'
    if any(v in s for v in ('/archive/','/retired/','/tests/','/test_')): return 'historical_reference'
    if re.search(r'transaction|rollback|recovery|restore|backup',s): return 'recovery_rollback_record_requires_review'
    if re.search(r'compose|manifest|/etc/lifeos/|/deploy-triggers/',s): return 'deployment_record_requires_review'
    return 'generic_predbat_mention'

def read_small(path):
    p=pathlib.Path(path)
    if p.is_symlink() or not stat.S_ISREG(p.stat().st_mode): raise ValueError('non_regular_or_symlink_requires_manual_review')
    with p.open('rb') as f: data=f.read(LIMIT+1)
    if len(data)>LIMIT: raise ValueError('over_1MiB')
    return data.decode('utf-8','strict')

def archive_child(path):
    # Child is killed by parent after eight seconds. No extract/extractall.
    out=[]; count=0; used=0
    def take(name,size,reader):
        nonlocal count,used
        count+=1
        if count>2000: raise ValueError('archive_member_budget')
        pr=priority(name)
        if pr not in ('transaction_record','configuration_or_recovery_record','executable_or_policy_record'): return
        if size>LIMIT: out.append({'member':name,'error':'over_1MiB'}); return
        used+=size
        if used>8*LIMIT: raise ValueError('archive_read_budget')
        raw=reader.read(LIMIT+1)
        if len(raw)>LIMIT: raise ValueError('archive_member_over_budget')
        # Private child output goes to private local report, never stdout summary.
        out.append({'member':name,'text':raw.decode('utf-8','strict')})
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                if len(z.infolist())>2000: raise ValueError('archive_member_budget')
                for m in z.infolist():
                    if not m.is_dir():
                        if m.flag_bits&1: out.append({'member':m.filename,'error':'encrypted_member'}); continue
                        if priority(m.filename) in ('transaction_record','configuration_or_recovery_record','executable_or_policy_record'):
                            with z.open(m) as f: take(m.filename,m.file_size,f)
        else:
            with tarfile.open(path,'r:*') as t:
                for m in t:
                    count+=1
                    if count>2000: raise ValueError('archive_member_budget')
                    if m.issym() or m.islnk(): out.append({'member':m.name,'error':'archive_link_not_followed'}); continue
                    if m.isfile() and priority(m.name) in ('transaction_record','configuration_or_recovery_record','executable_or_policy_record'):
                        f=t.extractfile(m)
                        if f:
                            with f: take(m.name,m.size,f)
        print(json.dumps({'members':out,'coverage':'TARGETED_MEMBERS_ONLY'}))
    except Exception as e: print(json.dumps({'error':type(e).__name__}))

def command(args,timeout=15):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return {'ok':p.returncode==0,'stdout':p.stdout if p.returncode==0 else '', 'error':None if p.returncode==0 else 'exit_'+str(p.returncode)}
    except (OSError,subprocess.TimeoutExpired) as e: return {'ok':False,'stdout':'','error':type(e).__name__}

def check_schema(d):
    for k in ('inventory','reference_hits','coverage_gaps','reference_roots','errors','growth'):
        if not isinstance(d.get(k),list): raise ValueError('invalid_or_missing_list:'+k)
    settings(d)
    rows=d['inventory']; seen=set()
    for r in rows:
        short=r.get('short_id'); full=r.get('id','')
        if short in seen or not re.fullmatch(r'sha256:[a-f0-9]{64}',full) or not full[7:].startswith(short): raise ValueError('invalid_image_identity')
        seen.add(short)
    if len(EXPECTED)!=20 or len(PINS)!=4 or seen!=EXPECTED|PINS: raise ValueError('inventory_does_not_match_20_candidates_and_4_protected')
    for h in d['reference_hits']:
        if not isinstance(h.get('path'),str) or not isinstance(h.get('matched_tokens'),list) or not all(isinstance(x,str) for x in h['matched_tokens']): raise ValueError('invalid_reference_hit')
    return [r for r in rows if r['short_id'] in EXPECTED]

def main(input_path,outdir):
    start=time.monotonic(); output=pathlib.Path(outdir)
    if pathlib.Path(input_path).stat().st_size>16*LIMIT: raise ValueError('input_over_16MiB')
    raw=pathlib.Path(input_path).read_bytes(); d=json.loads(raw); rows=check_schema(d)
    required_path(STORAGE_ROOT,'PREDBAT_STORAGE_ROOT')
    required_path(TRANSACTION_ROOT,'PREDBAT_TRANSACTION_ROOT')
    image_events={'ok':False,'stdout':'','error':'baseline_timestamp_unavailable'}
    try:
        since=datetime.datetime.fromisoformat(d['timestamp_utc'])
        if since.tzinfo is not None:
            until=datetime.datetime.now(datetime.timezone.utc).isoformat()
            image_events=command(['docker','events','--since',since.isoformat(),'--until',until,
                '--filter','type=image','--format','{{json .}}'],timeout=3)
    except (KeyError,TypeError,ValueError): pass
    directory_metadata=[]
    metadata_dirs=json.loads(os.environ.get('PREDBAT_METADATA_DIRS','[]'))
    if not isinstance(metadata_dirs,list) or len(metadata_dirs)>8: raise ValueError('invalid_metadata_directories')
    for path in metadata_dirs:
        required_path(path,'metadata_directory')
        try:
            st=os.stat(path); directory_metadata.append({'path':path,'mtime_ns':st.st_mtime_ns,'inode':st.st_ino,'size_not_measured':True})
        except OSError: directory_metadata.append({'path':path,'error':'inaccessible','size_not_measured':True})
    roots=[pathlib.Path(r) for r in d['reference_roots'] if pathlib.Path(r).is_absolute()]
    def scoped(p): return any(pathlib.Path(p).is_relative_to(r) for r in roots)
    token_hits=[]; original=[]; skips=[]; rescans=[]
    for h in d['reference_hits']:
        matches=candidate_matches('\n'.join(h['matched_tokens']),rows)
        if matches: token_hits.append({'path':h['path'],'candidates':matches})
        original.append({'path':h['path'],'token_matches':matches,'generic_flag':h.get('generic_predbat_reference')})
    priorities=collections.Counter(priority(g['path']) for g in d['coverage_gaps'] if 'path' in g)
    targets={h['path'] for h in original}
    for g in d['coverage_gaps']:
        p=g.get('path','')
        if priority(p) not in ('irrelevant_binary','unrelated_dependency_or_asset','unrelated_document_media'): targets.add(p)
    # Probe the known transaction descriptors, without walking application data.
    tx=pathlib.Path(required_path(TRANSACTION_ROOT,'PREDBAT_TRANSACTION_ROOT'))
    try:
        with os.scandir(tx) as it:
            for i,e in enumerate(it):
                if i>=128: skips.append({'path':str(tx),'reason':'transaction_count_budget'}); break
                if e.is_dir(follow_symlinks=False):
                    targets.update([str(pathlib.Path(e.path)/'manifest.json'),str(pathlib.Path(e.path)/'backups/target')])
    except OSError: skips.append({'path':str(tx),'reason':'transaction_directory_inaccessible'})
    used=0; done=0; archives=0
    ordered=sorted(targets,key=lambda p:(0 if priority(p)=='transaction_record' else 1 if re.search(r'compose|rollback|configuration\.tar',p,re.I) else 2,p))
    for path in ordered:
        if done>=400 or used>=24*LIMIT or time.monotonic()-start>110:
            skips.append({'path':path,'reason':'global_followup_budget'}); continue
        pr=priority(path)
        if not scoped(path): skips.append({'path':path,'reason':'outside_original_roots'}); continue
        if pr in ('irrelevant_binary','unrelated_dependency_or_asset','unrelated_document_media'): continue
        if pathlib.Path(path).is_dir():
            skips.append({'path':path,'reason':'directory_requires_targeted_descriptor_review'}); continue
        if pr in ('configuration_archive','opaque_archive_review'):
            try:
                if pathlib.Path(path).is_symlink() or not stat.S_ISREG(pathlib.Path(path).stat().st_mode):
                    skips.append({'path':path,'reason':'non_regular_archive'}); continue
            except OSError:
                skips.append({'path':path,'reason':'archive_inaccessible'}); continue
            if pr!='configuration_archive' or archives>=8:
                skips.append({'path':path,'reason':'opaque_or_archive_budget'}); continue
            archives+=1
            r=command([sys.executable,__file__,'--archive-child',path],timeout=8)
            if not r['ok']: skips.append({'path':path,'reason':'archive_'+str(r['error'])}); continue
            try: packet=json.loads(r['stdout'])
            except ValueError: skips.append({'path':path,'reason':'archive_bad_output'}); continue
            if packet.get('error'): skips.append({'path':path,'reason':packet['error']}); continue
            skips.append({'path':path,'reason':'archive_targeted_members_only_not_exhaustive'})
            for m in packet.get('members',[]):
                if 'text' not in m: skips.append({'path':path+'::'+m['member'],'reason':m.get('error','unread')}); continue
                text=m['text']; matches=candidate_matches(text,d['inventory'])
                rescans.append({'path':path+'::'+m['member'],'category':category(path,text,matches),
                                'image_matches':matches,'sha256':hashlib.sha256(text.encode()).hexdigest()})
            continue
        try:
            text=read_small(path); used+=len(text.encode()); done+=1
            matches=candidate_matches(text,d['inventory'])
            rescans.append({'path':path,'category':category(path,text,matches),'image_matches':matches,
                            'sha256':hashlib.sha256(text.encode()).hexdigest()})
        except (OSError,UnicodeError,ValueError) as e: skips.append({'path':path,'reason':type(e).__name__})
    bypath={r['path']:r for r in rescans}
    classified=collections.Counter(bypath[h['path']]['category'] if h['path'] in bypath else 'unverified_unreadable_or_budget' for h in original)
    newrefs=[{'path':r['path'],'category':r['category'],'candidates':[m for m in r['image_matches'] if m['short_id'] in EXPECTED]} for r in rescans if any(m['short_id'] in EXPECTED for m in r['image_matches'])]
    # No daemon-wide accounting, no full queues/backups scan; compare existing
    # exact allocated-byte roots with bounded low-priority du only for logs/recovery.
    growth=[]
    for path,baseline in growth_targets(d):
        if time.monotonic()-start>145: growth.append({'path':path,'error':'followup_time_budget'}); continue
        cmd=['nice','-n','19','du','-x','-B1','-s',path]
        if pathlib.Path('/usr/bin/ionice').exists(): cmd=['ionice','-c','3']+cmd
        r=command(cmd,timeout=8)
        try: current=int(r['stdout'].split()[0]) if r['ok'] else None
        except (ValueError,IndexError): current=None
        growth.append({'path':path,'baseline_owner_report_bytes':baseline,'current_allocated_bytes':current,
                       'delta_from_owner_report':None if current is None or baseline is None else current-baseline,'error':r['error']})
    fs=os.statvfs(required_path(STORAGE_ROOT,'PREDBAT_STORAGE_ROOT')); avail=fs.f_bavail*fs.f_frsize; reserve=(fs.f_blocks*fs.f_frsize+9)//10
    # Re-read container/image identity only; no logs or document contents.
    cs=command(['docker','ps','-aq','--no-trunc']); current=[]
    if cs['ok']:
        for cid in cs['stdout'].split():
            if time.monotonic()-start>160:
                skips.append({'path':'container_inspection','reason':'time_budget'}); break
            fmt='{"id":{{json .Id}},"image":{{json .Image}},"started":{{json .State.StartedAt}},"status":{{json .State.Status}},"restarts":{{json .RestartCount}}}'
            r=command(['docker','inspect','--type','container','--format',fmt,cid],timeout=3)
            try: current.append(json.loads(r['stdout']) if r['ok'] else {'id':cid,'error':r['error']})
            except ValueError: current.append({'id':cid,'error':'invalid_inspect_json'})
    oldcontainers=d.get('containers')
    before_compare=None
    if isinstance(oldcontainers,list):
        fields=('id','image','started','status','restarts')
        before_compare=sorted([{k:c.get(k) for k in fields} for c in oldcontainers],key=lambda x:x['id'])
    current_compare=sorted(current,key=lambda x:x['id'])
    unchanged=before_compare is not None and cs['ok'] and current_compare==before_compare
    images_now=[]
    for old in d['inventory']:
        if old['short_id'] not in PINS|({FOCUS_ID} if FOCUS_ID else set()): continue
        if time.monotonic()-start>170:
            skips.append({'path':'image_inspection','reason':'time_budget'}); break
        fmt='{"id":{{json .Id}},"tags":{{json .RepoTags}},"registry_digests":{{json .RepoDigests}},"total_size_bytes":{{json .Size}}}'
        r=command(['docker','image','inspect','--format',fmt,old['id']],timeout=2)
        try:
            now=json.loads(r['stdout']) if r['ok'] else {'error':r['error']}
        except ValueError: now={'error':'invalid_image_json'}
        now['short_id']=old['short_id']; now['identity_matches_original']=now.get('id')==old['id']
        images_now.append(now)
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    detailed={'timestamp_utc':timestamp,'input_sha256':hashlib.sha256(raw).hexdigest(),'schema_validated':True,
        'original_token_candidate_hits':token_hits,'original_hits':original,'original_hit_class_counts':dict(classified),
        'gap_priority_counts':dict(priorities),'targeted_file_results':rescans,'targeted_candidate_references':newrefs,
        'unresolved':skips,'growth':growth,'docker_image_events_since_original':image_events,
        'backup_queue_directory_metadata_only':directory_metadata,
        'current_containers':current,'focused_image_recheck':images_now,
        'container_identity_unchanged_from_original':unchanged,
        'filesystem':{'available_bytes':avail,'reserve_bytes':reserve,'headroom_bytes':avail-reserve},
        'approved_deletion_allowlist':[],'decision':'NO_GO_PENDING_RECOVERY_REVIEW'}
    (output/'details-private.json').write_text(json.dumps(detailed,indent=2))
    summary={'timestamp_utc':timestamp,'schema_validated':True,'inventory_count':len(d['inventory']),
        'original_hit_count':len(original),'original_candidate_token_hit_count':len(token_hits),
        'original_hit_class_counts':dict(classified),'generic_flag_count':sum(bool(h['generic_flag']) for h in original),
        'original_gap_priority_counts':dict(priorities),'targeted_files_read':done,'archives_attempted':archives,
        'targeted_candidate_reference_count':len(newrefs),'unresolved_counts':dict(collections.Counter(x['reason'] for x in skips)),
        'collector_error_counts':dict(collections.Counter(x.get('error','unknown') for x in d['errors'])),
        'docker_image_event_query_ok':image_events['ok'],
        'docker_image_event_lines':len(image_events['stdout'].splitlines()),
        'backup_queue_sizes':'NOT_RESCANNED_DIRECTORY_METADATA_ONLY',
        'growth_measured_deltas':[{'area':pathlib.Path(x['path']).name,'allocated_bytes':x.get('current_allocated_bytes'),
            'delta_from_owner_report':x.get('delta_from_owner_report'),'error':x.get('error')} for x in growth],
        'filesystem':detailed['filesystem'],'container_identity_unchanged_from_original':unchanged,
        'approved_deletion_allowlist':[],'decision':detailed['decision'],
        'historical_storage_growth_cause':'UNRESOLVED_UNLESS_COMPARABLE_BASELINE_ESTABLISHES_IT',
        'note':'Classification is triage, not proof of dependency or absence; private details remain on Pi.'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--archive-child': archive_child(sys.argv[2])
    else:
        try: main(sys.argv[1],sys.argv[2])
        except Exception as e:
            print('FOLLOWUP_FAILED='+type(e).__name__+':'+str(e)); sys.exit(1)
