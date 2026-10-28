"""Conservative source-only guards for optional/non-obligation email.

A source disposition never proves an obligation complete. Unknown/transactional
or mixed-source evidence remains untouched. No private text leaves this module.
"""
import html
import re

KINDS = {"marketing_offer", "routine_delivery", "optional_opportunity"}


def _text(message):
    text = "\n".join(str(message.get(key) or "") for key in ("subject", "snippet", "body", "text"))
    text = html.unescape(text)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).replace("’", "'").strip()


def non_obligation_decision(message):
    """Return kind/reason enums only, never source text or model guesses."""
    text = _text(message)
    subject = html.unescape(str(message.get("subject") or ""))
    bulk = bool(message.get("bulk_mail")) or bool(re.search(r"\b(?:unsubscribe|newsletter|manage (?:email )?preferences)\b", text, re.I))
    # Mandatory follow-up and delivery exceptions outrank campaign/template cues.
    required = re.search(r"\b(?:action (?:is )?required|requires your (?:action|response)|you (?:must|need to|are required to)\s+(?:pay|sign|submit|provide|attend|respond|apply|renew|reply|collect)|please\s+(?:provide|send|pay|sign|confirm|correct|upload|track|investigate|check|settle|renew|respond|reply|return|complete|verify|repay)|signature required|reschedule|delivery (?:(?:is|has been) )?(?:failed|exception|problem|attempted|delayed)|(?:could not|couldn't|unable to) deliver|collect (?:your|the) (?:parcel|package)|customs (?:fee|charge))\b", text, re.I)
    if required:
        return None,"mandatory_request"
    # Real application/booking/claim activity is not a voluntary invitation.
    committed = re.search(r"\b(?:(?:you|I|we)(?:'ve| have| already)\s+(?:applied|booked|accepted|registered|confirmed)|your (?:application|booking|appointment|claim|appeal|complaint)\s+(?:has|is|was|will|needs|requires)|(?:application|booking|claim|case) (?:reference|number|received|submitted)|interview (?:invitation|scheduled)|invitation to interview)\b", text, re.I)
    if committed:
        return None,"accepted_commitment"
    obligation = re.search(r"\b(?:(?:invoice|payment|balance|instalment|installment|rent|bill)\s+(?:(?:is|are|will be)\s+)?(?:due|overdue|outstanding|required|unpaid)|invoice (?:number|reference)|amount due|outstanding balance|your (?:current|existing) policy|your policy (?:expires|ends|renews)|renewal (?:notice|invitation)|certificate of (?:motor )?insurance|policy (?:has been issued|is now active)|(?:complaint|claim|case) (?:reference|number)|thank you for (?:applying|your application)|return (?:your|the) (?:old |loan |loaned )?(?:device|equipment))\b",text,re.I)
    sensitive_subject = re.search(r"\b(?:refund|chargeback|complaint|appeal|settlement|dispute|appointment|interview|invoice|payment|bill|renewal|policy|proof|identification|identity|your application|application (?:update|status|reference))\b",subject,re.I)
    if obligation or sensitive_subject:
        return None,"transactional_or_subject_uncertainty"
    delivery = re.search(r"\b(?:track (?:your|the) (?:order|parcel|package|delivery)|(?:order|parcel|package|delivery)\s+(?:is (?:now )?(?:on (?:its|the) way|out for delivery)|has (?:been (?:dispatched|delivered)|shipped)|will be delivered)|delivery (?:status|update|confirmation))\b", text, re.I)
    if delivery:
        return "routine_delivery","routine_delivery"
    promotion = re.search(r"\b(?:\d{1,2}\s*%\s*off|discount (?:code|offer)|promo(?:tional)? code|special offer|exclusive offer|claim (?:your )?(?:discount|offer|savings))\b", text, re.I)
    sales = re.search(r"\b(?:claim|redeem|shop|sale|use (?:the |your )?code|order now|offer)\b", text, re.I)
    if promotion and (bulk or sales):
        return "marketing_offer","marketing_offer"
    opportunity = re.search(r"\b(?:applications? (?:are )?(?:now )?open|apply (?:now|today|by|to (?:be|become))|(?:job|career|board|volunteer) opportunit(?:y|ies)|vacanc(?:y|ies)|join our (?:board|team))\b", text, re.I)
    invitation = re.search(r"\b(?:if you(?:'re| are) interested|we (?:invite|encourage) you to apply|would you like to|opportunity to apply)\b", text, re.I)
    if opportunity and (bulk or invitation):
        return "optional_opportunity","optional_opportunity"
    return None,"unclassified"


def non_obligation_kind(message):
    return non_obligation_decision(message)[0]


def task_quality_category(task):
    """Selection/aggregate diagnostics only; titles never authorise suppression."""
    text = " ".join(str(task.get(key) or "") for key in ("title", "topic"))
    if re.search(r"\b(?:discount|offer|claim)\b|%", text, re.I):
        return "marketing_offer"
    if re.search(r"\b(?:delivery|parcel|tracking|track)\b", text, re.I):
        return "routine_delivery"
    if re.search(r"\b(?:apply|application|opportunity|vacancy|director|board)\b", text, re.I):
        return "optional_opportunity"
    return None
