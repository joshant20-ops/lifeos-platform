"""Conservative source-only guards for optional/non-obligation email.

A source disposition never proves an obligation complete. Unknown/transactional
or mixed-source evidence remains untouched. No private text leaves this module.
"""
import html
import re
from datetime import date

KINDS = {"marketing_offer", "routine_delivery", "optional_opportunity", "optional_feedback", "optional_change_window"}


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
    # A polite survey invitation is not an obligation. Strong personal duties
    # still win, including a real duty embedded beside an optional invitation.
    strong_required = re.search(r"\b(?:must\b|shall\b|mandatory\b|compulsory\b|action (?:is )?required|requires your (?:action|response)|you (?:need to|are required to)\b|signature required|reschedule|delivery (?:(?:is|has been) )?(?:failed|exception|problem|attempted|delayed)|(?:could not|couldn't|unable to) deliver|customs (?:fee|charge))", text, re.I)
    if strong_required:
        return None,"mandatory_request"
    # Real application/booking/claim activity is not a voluntary invitation.
    committed = re.search(r"\b(?:(?:you|I|we)(?:'ve| have| already)\s+(?:applied|booked|accepted|registered|confirmed)|your (?:application|booking|appointment|claim|appeal|complaint)\s+(?:has|is|was|will|needs|requires)|(?:application|booking|claim|case) (?:reference|number|received|submitted)|interview (?:invitation|scheduled)|invitation to interview)\b", text, re.I)
    if committed:
        return None,"accepted_commitment"
    obligation = re.search(r"\b(?:(?:invoice|payment|balance|instalment|installment|rent|bill)\s+(?:(?:is|are|will be)\s+)?(?:due|overdue|outstanding|required|unpaid)|invoice (?:number|reference)|amount due|outstanding balance|your (?:current|existing) policy|your policy (?:expires|ends|renews)|renewal (?:notice|invitation)|certificate of (?:motor )?insurance|policy (?:has been issued|is now active)|(?:complaint|claim|case) (?:reference|number)|thank you for (?:applying|your application)|return (?:your|the) (?:old |loan |loaned )?(?:device|equipment))\b",text,re.I)
    sensitive_subject = re.search(r"\b(?:refund|chargeback|complaint|appeal|settlement|dispute|appointment|interview|invoice|payment|bill|renewal|policy|proof|identification|identity|your application|application (?:update|status|reference))\b",subject,re.I)
    if obligation or sensitive_subject:
        return None,"transactional_or_subject_uncertainty"
    feedback = re.search(r"\b(?:(?:please\s+)?rate\s+(?:your|the|our)\s+(?:meals?|menu|delivery|experience|purchase|order|service)|(?:please\s+)?(?:complete|take|fill (?:in|out))\s+(?:(?:our|a|the|this|your|short|quick|optional|voluntary)\s+)*(?:survey|questionnaire)|(?:we'd|we would) love (?:your|to hear your) feedback)\b", text, re.I)
    if feedback and re.search(r"\b(?:survey|questionnaire)\b",feedback.group()) and not re.search(r"\b(?:optional|voluntary|customer satisfaction|meals?|menu|food)\b",text,re.I):
        feedback=None
    conditional_duty = re.search(r"\b(?:as a condition|before your (?:operation|surgery|treatment|appointment)|licen[cs]e|medical|consent|identification|identity|entitlement|allergen|unless|to receive|(?:cannot|can't|will not|won't)\b.{0,60}\buntil)\b",text,re.I)
    if conditional_duty:
        return None,"transactional_or_subject_uncertainty"
    change = re.search(r"\b(?:(?:if you(?:'d| would) like|if you want)\s+to\s+(?:make|change|edit|update|skip|pause)|you can\s+(?:still\s+)?(?:change|edit|update|skip|pause)|(?:last chance|cut[- ]?off|deadline)\s+(?:for|to)\s+(?:make |making )?(?:changes|edit|change|update|skip))\b", text, re.I)
    meal_or_order = re.search(r"\b(?:meals?|menu|meal plan|food box|weekly box|order)\b", text, re.I)
    # Remove only the matched optional invitation before testing for a second,
    # concrete request. A promotional footer cannot hide that separate duty.
    optional = feedback or (change if meal_or_order else None)
    if optional:
        remainder = text[:optional.start()] + text[optional.end():]
        other_request = re.search(r"(?:\bplease\s+|\b(?:and|then|also)\s+|^|[.!;,:]\s*)(?:provide|send|pay|sign|confirm|correct|upload|track|investigate|check|settle|renew|respond|reply|return|complete|verify|repay|submit|file|prepare|update|edit|approve|accept)\b", remainder, re.I)
        if not other_request:
            kind = "optional_feedback" if feedback else "optional_change_window"
            return kind,kind
    if required:
        return None,"mandatory_request"
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


def event_source_evidence(message, due_date=None):
    """Return safe booleans for a scheduled event/date and separate action signal."""
    text = _text(message)
    event = re.search(r"\b(?:hearing|appointment|meeting)\b", text, re.I)
    deadline_phrase = re.search(r"\b(?:evidence|submission|response|filing|payment|invoice|application|claim|documents?|deadline|time limit)\b.{0,60}\b(?:closes?|closing|ends?|due|required|outstanding|expires?|payable|return by|no later than)\b",text,re.I)
    action = re.search(r"\b(?:deadline|you (?:must|shall|need to|are required to)\s+(?:pay|submit|provide|send|prepare|file|respond|reply|confirm|complete|sign|attend)|please\s+(?:pay|submit|provide|send|prepare|file|respond|reply|confirm|complete|sign|attend)|(?:pay|submit|provide|send|prepare|file|respond|reply|confirm|complete|sign)\s+(?:your|the|this|evidence|documents?)|(?:invoice|payment|balance|bill|submission|response|evidence|documents?|consent|fee)\s+(?:is |are )?(?:due|required|outstanding))\b", text,re.I)
    action_deadline = bool(deadline_phrase or (action and re.search(r"\b(?:by|before|until|within\s+\d+\s+(?:days?|weeks?)|deadline|due|no later than)\b",text,re.I)))
    action = action or deadline_phrase
    scheduled = re.search(r"\b(?:scheduled|will (?:be held|take place)|listed for|arranged|(?:hearing|appointment|meeting)\s+(?:on|at|date|:)|date of (?:the )?(?:hearing|appointment|meeting))\b", text, re.I)
    if not event or not scheduled:
        return {"event_scheduled":False,"event_date_matches":False,"event_action_signal":bool(action),"event_action_deadline":action_deadline}
    matches_due = False
    try:
        expected = date.fromisoformat(str(due_date))
    except (TypeError,ValueError):
        expected = None
    if expected:
        start=max(0,event.start()-80)
        stop=min(len(text),max(event.end(),scheduled.end())+160)
        context=text[start:stop]
        date_tokens=[]
        date_tokens.extend(re.findall(r"\b\d{4}-\d{2}-\d{2}\b",context))
        date_tokens.extend(m.group(0) for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s/-]+(\d{1,2})[\s/-]+(\d{2,4})\b",context,re.I))
        month=r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        date_tokens.extend(m.group(0) for m in re.finditer(r"\b(?:\d{1,2}(?:st|nd|rd|th)?\s+"+month+r"(?:\s+\d{2,4})?|"+month+r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{2,4})?)\b",context,re.I))
        for token in date_tokens:
            candidate=None
            try:candidate=date.fromisoformat(token)
            except ValueError:pass
            if candidate is None:
                digits=re.fullmatch(r"(\d{1,2})[\s/-]+(\d{1,2})[\s/-]+(\d{2,4})",token)
                if digits:
                    a,b,y=map(int,digits.groups())
                    if y<100:y+=2000
                    for day,month_num in ((a,b),(b,a)):
                        try:candidate=date(y,month_num,day);break
                        except ValueError:continue
            if candidate is None:
                clean=re.sub(r"(\d)(st|nd|rd|th)\b",r"\1",token,flags=re.I).replace(",","")
                for fmt in ("%d %B %Y","%d %b %Y","%B %d %Y","%b %d %Y","%d %B","%d %b","%B %d","%b %d"):
                    try:
                        parsed=__import__("datetime").datetime.strptime(clean,fmt)
                        candidate=date(expected.year if "%Y" not in fmt else parsed.year,parsed.month,parsed.day)
                        break
                    except ValueError:continue
            if candidate==expected:
                matches_due=True
                break
    return {"event_scheduled":True,"event_date_matches":matches_due,"event_action_signal":bool(action),"event_action_deadline":action_deadline}


def event_notice(message):
    """Whether a source is a scheduled event notice without response signals."""
    evidence=event_source_evidence(message)
    return evidence.get("event_scheduled") and not evidence.get("event_action_signal")


def non_obligation_kind(message):
    return non_obligation_decision(message)[0]


def task_quality_category(task):
    """Selection/aggregate diagnostics only; titles never authorise suppression."""
    text = " ".join(str(task.get(key) or "") for key in ("title", "topic"))
    if re.search(r"\b(?:feedback|survey|questionnaire)\b|\brate\b.*\b(?:meals?|service|experience|delivery|order|purchase)\b", text, re.I):
        return "optional_feedback"
    if re.search(r"\b(?:meal|menu|order)\b.*\b(?:changes?|edit|skip|pause)\b", text, re.I):
        return "optional_change_window"
    if re.search(r"\b(?:hearing|appointment|meeting)\b", text, re.I) and not re.search(r"\b(?:submit|provide|pay|prepare|file|respond|reply|confirm)\b", text, re.I):
        return "scheduled_event"
    if re.search(r"\b(?:discount|offer|claim)\b|%", text, re.I):
        return "marketing_offer"
    if re.search(r"\b(?:delivery|parcel|tracking|track)\b", text, re.I):
        return "routine_delivery"
    if re.search(r"\b(?:apply|application|opportunity|vacancy|director|board)\b", text, re.I):
        return "optional_opportunity"
    return None
