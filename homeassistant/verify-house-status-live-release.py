#!/usr/bin/env python3
"""Fail-closed checks for the explicitly approved House Status production release."""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'homeassistant/releases/house-status/live/approved-release.json'
LIVE_CONFIG = REPO / 'homelab/live/opt/stacks/homeassistant/config/configuration.yaml'
V28 = REPO / 'homeassistant/releases/house-status/live/lifeos-house-status-v28.js'
PACKAGER_VERSION = 1

class GateError(Exception):
    pass

def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fail(msg: str) -> None:
    raise GateError(msg)

def verify_manifest(data: dict) -> dict:
    if data.get('schema_version') != 1:
        fail('unsupported_manifest_schema')
    approved = data.get('approved_production')
    if not isinstance(approved, dict):
        fail('no_explicitly_approved_release')
    previous=data.get('previous_production_release')
    previous_hash=data.get('previous_production_artifact_sha256')
    if not isinstance(previous,str) or not re.fullmatch(r'v\d+',previous):
        fail('previous_production_release_missing')
    if not isinstance(previous_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',previous_hash):
        fail('previous_production_artifact_hash_missing')
    next_release=data.get('next_candidate_release')
    if not isinstance(next_release,str) or not re.fullmatch(r'v(?:3[0-9]|[4-9][0-9]|[1-9][0-9]{2,})',next_release):
        fail('next_candidate_release_missing')
    if int(next_release[1:]) <= int(str(approved.get('release','v0'))[1:]):
        fail('next_candidate_release_not_newer_than_production')
    release = approved.get('release')
    if not isinstance(release, str) or not re.fullmatch(r'v\d+', release):
        fail('invalid_approved_release_identity')
    digest = approved.get('artifact_sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        fail('approved_artifact_identity_missing')
    if release == 'v28':
        if approved.get('artifact') != 'homeassistant/releases/house-status/live/lifeos-house-status-v28.js':
            fail('v28_artifact_path_mismatch')
        if sha(V28) != digest:
            fail('v28_artifact_sha256_mismatch')
        evidence = approved.get('acceptance') or {}
        if evidence.get('kind') != 'existing-live-baseline' or evidence.get('run_id') != 37233446561:
            fail('v28_baseline_acceptance_invalid')
    else:
        candidate = data.get('promotion_candidate')
        if not isinstance(candidate, dict):
            fail('promotion_candidate_record_missing')
        if candidate.get('release') != release or candidate.get('artifact_sha256') != digest:
            fail('candidate_not_explicitly_approved')
        if int(next_release[1:]) <= int(release[1:]):
            fail('next_candidate_release_not_newer_than_candidate')
        if candidate.get('packager_version') != PACKAGER_VERSION:
            fail('candidate_packager_version_mismatch')
        if not re.fullmatch(r'[0-9a-f]{40}', str(candidate.get('source_commit',''))):
            fail('candidate_source_commit_missing')
        if not re.fullmatch(r'[0-9a-f]{40}', str(candidate.get('packager_commit',''))):
            fail('candidate_packager_commit_missing')
        run_id=candidate.get('dev_acceptance_run_id')
        run_number=candidate.get('dev_acceptance_run_number')
        has_id='dev_acceptance_run_id' in candidate
        has_number='dev_acceptance_run_number' in candidate
        valid_id=type(run_id) is int and run_id > 0
        valid_number=type(run_number) is int and run_number > 0
        if has_id == has_number or (has_id and not valid_id) or (has_number and not valid_number):
            fail('candidate_dev_acceptance_identity_missing')
        if type(candidate.get('dev_acceptance_run_attempt')) is not int or candidate['dev_acceptance_run_attempt'] < 1:
            fail('candidate_dev_acceptance_attempt_missing')
        for key in ('dev_app_sha256','dev_doorbell_sha256','doorbell_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', str(candidate.get(key,''))):
                fail(f'candidate_{key}_missing')
    return approved

def select_release(data: dict, request_release: str, request_sha: str) -> dict:
    approved = verify_manifest(data)
    if not request_release or not request_sha:
        fail('explicit_release_and_sha256_required')
    if request_release != approved['release']:
        fail('requested_release_is_not_approved')
    if request_sha != approved['artifact_sha256']:
        fail('requested_artifact_identity_mismatch')
    return approved

def api_json(token: str, url: str) -> dict:
    req=urllib.request.Request(url,headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.loads(response.read())

def verify_baseline_acceptance(approved: dict, token: str, repo: str) -> None:
    evidence=approved.get('acceptance') or {}
    if evidence.get('kind')!='existing-live-baseline':
        fail('v28_baseline_acceptance_invalid')
    run=api_json(token,f'https://api.github.com/repos/{repo}/actions/runs/{evidence["run_id"]}')
    if run.get('name')!='House Status Live Deploy' or run.get('path')!='.github/workflows/house-status-live-deploy.yml':
        fail('baseline_evidence_is_not_house_status_live_workflow')
    if run.get('head_sha')!=evidence.get('head_sha') or run.get('run_attempt')!=evidence.get('run_attempt'):
        fail('baseline_evidence_identity_mismatch')
    if run.get('status')!='completed' or run.get('conclusion')!='success':
        fail('baseline_live_acceptance_not_successful')

def successful_dev_deploy_job(payload: dict, candidate: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
        fail('dev_jobs_response_invalid')
    expected = {
        'run_id': candidate['dev_acceptance_run_id'],
        'run_attempt': candidate['dev_acceptance_run_attempt'],
        'head_sha': candidate['source_commit'],
        'workflow_name': 'House Status Development Deploy',
    }
    jobs = [job for job in payload['jobs'] if isinstance(job, dict) and job.get('name') == 'deploy']
    if len(jobs) != 1:
        fail('successful_dev_deploy_job_missing')
    job = jobs[0]
    if any(job.get(key) != value for key, value in expected.items()):
        fail('dev_deploy_job_identity_mismatch')
    if job.get('status') != 'completed' or job.get('conclusion') != 'success':
        fail('successful_dev_deploy_job_missing')
    if not isinstance(job.get('id'), int) or job['id'] <= 0:
        fail('dev_deploy_job_id_missing')
    return job

def github_job_logs_api_url(repo: str, job: dict) -> str:
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        fail('invalid_github_repository')
    job_id = job.get('id') if isinstance(job, dict) else None
    if not isinstance(job_id, int) or job_id <= 0:
        fail('dev_deploy_job_id_missing')
    return f'https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs'

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep GitHub API credentials on the API request, never a signed redirect."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def fetch_github_job_logs(token: str, url: str) -> bytes:
    req=urllib.request.Request(url,headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json'})
    opener=urllib.request.build_opener(_NoRedirectHandler)
    try:
        with opener.open(req,timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as response:
        if response.code not in (301,302,303,307,308):
            raise
        location=response.headers.get('Location')
        response.close()
    if not location:
        fail('dev_deploy_job_logs_redirect_location_missing')
    signed_url=urllib.parse.urljoin(url,location)
    if urllib.parse.urlsplit(signed_url).scheme!='https':
        fail('dev_deploy_job_logs_redirect_not_https')
    # The signed URL authorizes this fetch. Do not attach GitHub credentials.
    signed_req=urllib.request.Request(signed_url,headers={'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(signed_req,timeout=30) as response:
        return response.read()

def successful_dev_run_by_number(payload: dict, candidate: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get('workflow_runs'), list):
        fail('dev_runs_response_invalid')
    number=candidate.get('dev_acceptance_run_number')
    matches=[run for run in payload['workflow_runs']
             if isinstance(run,dict) and run.get('run_number')==number]
    if len(matches)!=1:
        fail('dev_acceptance_run_number_not_unique')
    run=matches[0]
    expected={
      'name':'House Status Development Deploy',
      'path':'.github/workflows/house-status-dev-deploy.yml',
      'event':'push',
      'head_branch':'main',
      'head_sha':candidate['source_commit'],
      'run_attempt':candidate['dev_acceptance_run_attempt'],
      'status':'completed',
      'conclusion':'success',
    }
    if any(run.get(key)!=value for key,value in expected.items()):
        fail('dev_acceptance_run_number_identity_mismatch')
    if type(run.get('id')) is not int or run['id']<1:
        fail('dev_acceptance_run_id_missing')
    return run

def verify_dev_acceptance(candidate: dict, token: str, repo: str) -> None:
    base=f'https://api.github.com/repos/{repo}/actions'
    if 'dev_acceptance_run_id' in candidate:
        run=api_json(token,f'{base}/runs/{candidate["dev_acceptance_run_id"]}')
    else:
        query=urllib.parse.urlencode({
            'branch':'main',
            'event':'push',
            'head_sha':candidate['source_commit'],
            'per_page':100,
        })
        runs_url=f'{base}/workflows/374218333/runs?{query}'
        run=successful_dev_run_by_number(api_json(token,runs_url),candidate)
    run_id=run.get('id')
    candidate_for_job=dict(candidate)
    candidate_for_job['dev_acceptance_run_id']=run_id
    jobs_payload=api_json(token,f'{base}/runs/{run_id}/attempts/{candidate["dev_acceptance_run_attempt"]}/jobs')
    job=successful_dev_deploy_job(jobs_payload,candidate_for_job)
    raw=fetch_github_job_logs(token,github_job_logs_api_url(repo,job))
    content=[]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            content.extend(archive.read(n).decode('utf-8','replace') for n in archive.namelist())
    except zipfile.BadZipFile:
        content.append(raw.decode('utf-8','replace'))
    validate_dev_evidence(candidate,run,'\n'.join(content))

def validate_dev_evidence(candidate: dict, run: dict, logs: str) -> None:
    if run.get('name')!='House Status Development Deploy' or run.get('path')!='.github/workflows/house-status-dev-deploy.yml':
        fail('acceptance_run_is_not_house_status_dev_workflow')
    if run.get('event')!='push' or run.get('head_branch')!='main' or run.get('head_sha')!=candidate['source_commit']:
        fail('acceptance_run_source_identity_mismatch')
    if run.get('status')!='completed' or run.get('conclusion')!='success' or run.get('run_attempt')!=candidate['dev_acceptance_run_attempt']:
        fail('acceptance_run_not_successful_or_attempt_mismatch')
    required=('HOUSE_STATUS_DEV_SERVED_ASSET=PASS','HOUSE_STATUS_DEV_LIVE_ACCEPTANCE=PASS',
              'HOUSE_STATUS_DEV_ROLLING_WEEK_MONTH_YEAR=PASS','YEAR_POWER_DOWN_RENDERING=HIDDEN')
    for marker in required:
        if marker not in logs:
            fail('dev_acceptance_evidence_marker_missing:'+marker)
    match=re.search(r'HOUSE_STATUS_RELEASE_ATTESTATION=(\{[^\r\n]+\})',logs)
    if not match:
        fail('dev_release_attestation_missing')
    attestation=json.loads(match.group(1))
    expected={
      'packager_version':candidate['packager_version'],
      'release':candidate['release'],
      'source_commit':candidate['source_commit'],
      'packager_commit':candidate['packager_commit'],
      'dev_app_sha256':candidate['dev_app_sha256'],
      'dev_doorbell_sha256':candidate['dev_doorbell_sha256'],
      'live_app_sha256':candidate['artifact_sha256'],
      'live_doorbell_sha256':candidate['doorbell_sha256'],
    }
    if any(attestation.get(k)!=v for k,v in expected.items()):
        fail('dev_acceptance_artifact_identity_mismatch')
    served=re.search(r'HOUSE_STATUS_DEV_SERVED_SHA256=([0-9a-f]{64})',logs)
    if not served or served.group(1)!=candidate['dev_app_sha256']:
        fail('browser_served_dev_hash_not_attested')

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',type=pathlib.Path,default=MANIFEST)
    ap.add_argument('--request-release')
    ap.add_argument('--request-sha256')
    ap.add_argument('--verify-dev-evidence',action='store_true')
    args=ap.parse_args()
    data=json.loads(args.manifest.read_text())
    approved=select_release(data,args.request_release,args.request_sha256)
    print(f'HOUSE_STATUS_APPROVED_RELEASE={approved["release"]}')
    print(f'HOUSE_STATUS_APPROVED_ARTIFACT_SHA256={approved["artifact_sha256"]}')
    if args.verify_dev_evidence and approved['release']!='v28':
        token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        repo=os.environ.get('GITHUB_REPOSITORY')
        if not token or not repo: fail('github_actions_read_token_missing')
        verify_dev_acceptance(data['promotion_candidate'],token,repo)
        print('HOUSE_STATUS_DEV_ACCEPTANCE_EVIDENCE=PASS')
    elif args.verify_dev_evidence:
        token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        repo=os.environ.get('GITHUB_REPOSITORY')
        if not token or not repo: fail('github_actions_read_token_missing')
        verify_baseline_acceptance(approved,token,repo)
        print('HOUSE_STATUS_APPROVED_BASELINE_ACCEPTANCE=PASS')
    return 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (GateError, OSError, json.JSONDecodeError, urllib.error.URLError, KeyError) as exc:
        print(f'HOUSE_STATUS_LIVE_RELEASE_GATE=FAIL:{exc}',file=sys.stderr)
        raise SystemExit(1)
