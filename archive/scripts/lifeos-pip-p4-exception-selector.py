#!/usr/bin/env python3
"""P4 exception selector using the accepted P2 native Paperless evaluator.

Executed inside the Paperless Django shell. Private document/taxonomy values
remain local. No Paperless writes are performed.
"""
from __future__ import annotations

p2_source=open("/tmp/lifeos-pip-p2-lib.py").read()
p2_library=p2_source.rsplit("\nmain()",1)[0]
exec(p2_library,globals())

documents=list(
    Document.objects.order_by("pk")
    .select_related("correspondent","document_type","storage_path")
    .prefetch_related("tags")
)
sample,_=representative_sample(documents)
classifier=load_classifier()
dimensions=(
    (Correspondent,False),
    (DocumentType,False),
    (Tag,True),
    (StoragePath,False),
)
rules_by_model={}
auto_by_model={}
for model,_ in dimensions:
    rules_by_model[model]=explicit_rules(model)
    auto_by_model[model]=list(model.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk"))

def resolved(document):
    for model,_ in dimensions:
        if native_matches(rules_by_model[model],document):
            return True
    if classifier is not None:
        for model,_ in dimensions:
            auto=auto_by_model[model]
            if not auto:
                continue
            if model is Correspondent:
                pred=classifier.predict_correspondent(document.suggestion_content)
                if any(r.pk==pred for r in auto): return True
            elif model is DocumentType:
                pred=classifier.predict_document_type(document.suggestion_content)
                if any(r.pk==pred for r in auto): return True
            elif model is Tag:
                pred=set(classifier.predict_tags(document.suggestion_content))
                if any(r.pk in pred for r in auto): return True
            elif model is StoragePath:
                pred=classifier.predict_storage_path(document.suggestion_content)
                if any(r.pk==pred for r in auto): return True
    return False

unresolved=[d.pk for d in sample if not resolved(d)]
print(f"P4_SAMPLE_DOCUMENTS={len(sample)}")
print(f"P4_NATIVE_RESOLVED={len(sample)-len(unresolved)}")
print(f"P4_UNRESOLVED_SELECTED={len(unresolved)}")
print("P4_SELECTOR=PAPERLESS_NATIVE_EXCEPTION_ONLY")
print("P4_DOCUMENT_MUTATION=NONE")
print("P4_PRIVATE_CONTENT_EMITTED=NONE")
print("RESULT=PASS")
