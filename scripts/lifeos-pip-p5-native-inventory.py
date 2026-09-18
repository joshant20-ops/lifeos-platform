#!/usr/bin/env python3
"""P5 progressive Paperless-first native inventory.

Runs inside Paperless. Reuses the accepted P2 native evaluator and emits only
document ID + native resolution state to a local file consumed by the P5 state
store. Nothing is written to Paperless and no private content is printed.
"""
p2_source=open("/tmp/lifeos-pip-p2-lib.py").read()
p2_library=p2_source.rsplit("\nmain()",1)[0]
exec(p2_library,globals())

documents=list(Document.objects.order_by("pk").select_related("correspondent","document_type","storage_path").prefetch_related("tags"))
classifier=load_classifier()
dimensions=(Correspondent,DocumentType,Tag,StoragePath)
rules={m:explicit_rules(m) for m in dimensions}
autos={m:list(m.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk")) for m in dimensions}

def resolved(d):
    if any(native_matches(rules[m],d) for m in dimensions): return True
    if not classifier: return False
    if autos[Correspondent] and any(r.pk==classifier.predict_correspondent(d.suggestion_content) for r in autos[Correspondent]): return True
    if autos[DocumentType] and any(r.pk==classifier.predict_document_type(d.suggestion_content) for r in autos[DocumentType]): return True
    if autos[Tag]:
        p=set(classifier.predict_tags(d.suggestion_content))
        if any(r.pk in p for r in autos[Tag]): return True
    if autos[StoragePath] and any(r.pk==classifier.predict_storage_path(d.suggestion_content) for r in autos[StoragePath]): return True
    return False

for d in documents:
    print(f"{d.pk}\t"+("native_resolved" if resolved(d) else "semantic_pending"))
