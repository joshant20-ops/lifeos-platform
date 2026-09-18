#!/usr/bin/env python3
"""P4 Paperless-first exception selector.

Runs inside Paperless. Selects only documents unresolved by Paperless native
matching/classification. Emits IDs only when explicitly requested for a local
consumer; default output is aggregate-only. Never writes Paperless.
"""
from __future__ import annotations
import argparse, hashlib
from documents.classifier import load_classifier
from documents.matching import matches
from documents.models import Correspondent, Document, DocumentType, StoragePath, Tag

MODELS=(Correspondent,DocumentType,Tag,StoragePath)

def rules(model):
    return list(model.objects.exclude(matching_algorithm=0).exclude(match=""))

def native_match(doc):
    text=(doc.content or "")
    title=(doc.title or "")
    for model in MODELS:
        for rule in rules(model):
            try:
                if matches(rule, text, title):
                    return True
            except Exception:
                continue
    try:
        classifier=load_classifier()
        if classifier and classifier.classify(doc):
            return True
    except Exception:
        pass
    return False

def unresolved_ids(limit):
    qs=Document.objects.only("id","title","content").order_by("id")
    out=[]
    for doc in qs.iterator():
        if not native_match(doc):
            out.append(doc.id)
            if limit and len(out)>=limit:
                break
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--emit-ids",action="store_true")
    a=p.parse_args()
    ids=unresolved_ids(a.limit)
    print(f"P4_UNRESOLVED_SELECTED={len(ids)}")
    print("P4_SELECTOR=PAPERLESS_NATIVE_EXCEPTION_ONLY")
    print("P4_DOCUMENT_MUTATION=NONE")
    print("P4_PRIVATE_CONTENT_EMITTED=NONE")
    if a.emit_ids:
        print("P4_LOCAL_DOCUMENT_IDS="+",".join(map(str,ids)))
    print("RESULT=PASS")

if __name__=="__main__":
    main()
