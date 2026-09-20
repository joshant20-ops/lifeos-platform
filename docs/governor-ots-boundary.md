# Governor / OTS engineering boundary

Issue: #764. Parent acceptance: #418. Level-1 proof: #759.

## Decision

Governor is the LifeOS control plane, not a coding-agent framework.

Governor **keeps**:
- job intake, durable state and observability;
- privacy classification and provider/builder routing;
- Tower lease / wake / release through the existing broker path;
- credential and capability boundaries;
- bounded patch publication and privileged deployment gates;
- independent local acceptance verification;
- evidence publication, archive and terminal disposition.

The selected OTS engineering agent (OpenHands on the local route; existing configured
adapter on other permitted routes) **owns**:
- repository inspection;
- engineering planning;
- source editing;
- test selection/execution;
- diagnosis;
- iterative repair inside the agent session.

## Removed overlap

The Governor no longer wraps the OTS engineering session in its own multi-iteration
plan/edit/test/retry loop. One governed job invokes one OTS engineering session. After
that session, Governor applies its publication/runtime gates and performs one independent
acceptance decision.

If acceptance fails, the job terminates with evidence. A caller may deliberately submit a
new governed job after the failed capability is understood; Governor does not silently
build a second autonomous coding loop around OpenHands.

The legacy helper functions for failure signatures and compatibility remain temporarily
while existing records/tests migrate, but they are no longer part of the primary
execution loop and are deletion candidates after the Level-1 proof.

## Security invariants

This refactor does not change:
- local-only work -> local builder/Tower route;
- cloud fallback prohibition for local-only work;
- Tower demand-power lifecycle;
- root broker allow-list;
- patch/runtime size/path validation;
- canonical repository publication checks;
- independent local verifier;
- no direct sudo assumption.

## Acceptance sequence

1. Deploy the refactored Governor through the existing bounded deployment workflow.
2. Run #759 as the deliberately trivial live proof.
3. Require the exact marker `LIFEOS_ISSUE_PICKUP_LEVEL1=PASS`, deterministic assertion,
   Governor/Tower/agent evidence, archived disposition and correct issue closure.
4. Only after #759 passes, advance through progressively harder acceptance workloads.
5. Close #764 only after the simplified path is live-proven; close #418 only after the
   overall issue-to-Engineer path has sufficient staged evidence.
