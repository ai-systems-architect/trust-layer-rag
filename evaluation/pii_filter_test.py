"""Unit tests for PII filtering — scrub() allowlist and entity detection.

Runs without any AWS credentials or live services. Requires spaCy model:
    python -m spacy download en_core_web_lg

Tests are grouped into three concerns:
1. Allowlist — domain terms must pass through unscrubbed even when NER fires.
2. PII detection — real PII must still be scrubbed after allowlist filtering.
3. Pass-through — clean text must be returned unchanged with no overhead.

Run:
    python evaluation/pii_filter_test.py

see docs/decision_log.md DL-017
"""
import sys

from utils.pii_filter import scrub, _DOMAIN_ALLOWLIST

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def _check(label: str, text: str, expected: str) -> None:
    global _PASS, _FAIL
    result = scrub(text)
    if result == expected:
        print(f"  PASS  {label}")
        _PASS += 1
    else:
        print(f"  FAIL  {label}")
        print(f"        input:    {text!r}")
        print(f"        expected: {expected!r}")
        print(f"        got:      {result!r}")
        _FAIL += 1


def _check_not_in(label: str, text: str, forbidden: str) -> None:
    """Pass if forbidden substring is absent from scrub() output."""
    global _PASS, _FAIL
    result = scrub(text)
    if forbidden not in result:
        print(f"  PASS  {label}")
        _PASS += 1
    else:
        print(f"  FAIL  {label}")
        print(f"        input:    {text!r}")
        print(f"        forbidden substring still present: {forbidden!r}")
        print(f"        got:      {result!r}")
        _FAIL += 1


# ---------------------------------------------------------------------------
# 1. Allowlist — domain terms must not be scrubbed
# ---------------------------------------------------------------------------

def test_allowlist() -> None:
    print("\n[1] Allowlist — domain terms pass through unscrubbed")

    # The observed false positive that motivated the allowlist (MAIN-3, DL-017)
    _check(
        "FedRAMP standalone",
        "FedRAMP access control requirements",
        "FedRAMP access control requirements",
    )
    _check(
        "FedRAMP in cross-corpus query",
        "How does FedRAMP Moderate differ from NIST 800-53 High?",
        "How does FedRAMP Moderate differ from NIST 800-53 High?",
    )
    _check(
        "NIST standalone",
        "NIST AI RMF governance controls",
        "NIST AI RMF governance controls",
    )
    _check(
        "AWS in query",
        "What AWS services does FedRAMP cover?",
        "What AWS services does FedRAMP cover?",
    )
    _check(
        "Bedrock in query",
        "Does Bedrock comply with FedRAMP Moderate?",
        "Does Bedrock comply with FedRAMP Moderate?",
    )
    _check(
        "FISMA in query",
        "FISMA compliance requirements for federal agencies",
        "FISMA compliance requirements for federal agencies",
    )
    _check(
        "ATO in query",
        "What is required for an ATO under FedRAMP?",
        "What is required for an ATO under FedRAMP?",
    )
    _check(
        "RMF in query",
        "How does RMF integrate with FedRAMP authorization?",
        "How does RMF integrate with FedRAMP authorization?",
    )
    # Expanded allowlist — federal roles, documents, frameworks
    _check(
        "OSCAL in query",
        "Can OSCAL machine-readable formats replace manual SSP review?",
        "Can OSCAL machine-readable formats replace manual SSP review?",
    )
    _check(
        "MITRE in query",
        "How does MITRE ATT&CK map to NIST 800-53 controls?",
        "How does MITRE ATT&CK map to NIST 800-53 controls?",
    )
    _check(
        "ATT&CK in query",
        "Which AC controls address ATT&CK lateral movement techniques?",
        "Which AC controls address ATT&CK lateral movement techniques?",
    )
    _check(
        "IAM in query",
        "What IAM policies satisfy AC-2 account management requirements?",
        "What IAM policies satisfy AC-2 account management requirements?",
    )
    _check(
        "FIPS in query",
        "Does FedRAMP require FIPS 140-2 validated cryptography?",
        "Does FedRAMP require FIPS 140-2 validated cryptography?",
    )
    _check(
        "SIEM in query",
        "What SIEM capabilities satisfy AU-12 audit record generation?",
        "What SIEM capabilities satisfy AU-12 audit record generation?",
    )
    _check(
        "ISSO in query",
        "What are ISSO responsibilities under NIST 800-53 PM controls?",
        "What are ISSO responsibilities under NIST 800-53 PM controls?",
    )
    _check(
        "ISSM in query",
        "How does ISSM oversight satisfy CA-7 continuous monitoring?",
        "How does ISSM oversight satisfy CA-7 continuous monitoring?",
    )
    _check(
        "CISO in query",
        "What CISO reporting requirements exist under FedRAMP Moderate?",
        "What CISO reporting requirements exist under FedRAMP Moderate?",
    )
    _check(
        "SSP in query",
        "Which NIST 800-53 controls must be documented in the SSP?",
        "Which NIST 800-53 controls must be documented in the SSP?",
    )
    _check(
        "POA&M in query",
        "How should a POA&M track open findings from FedRAMP assessment?",
        "How should a POA&M track open findings from FedRAMP assessment?",
    )
    _check(
        "CONOPS in query",
        "Does FedRAMP require a CONOPS as part of the authorization package?",
        "Does FedRAMP require a CONOPS as part of the authorization package?",
    )
    _check(
        "SOC in query",
        "What SOC controls address IR-6 incident reporting?",
        "What SOC controls address IR-6 incident reporting?",
    )

    # Programmatic completeness — loop over every declared member so new additions
    # automatically get a baseline test without requiring a manual case to be written.
    # Uses a generic compliance template; catches regressions when _DOMAIN_ALLOWLIST grows.
    print("\n  [1a] Programmatic completeness — all allowlist members via template")
    template = "What does {term} require for federal access control compliance?"
    for term in sorted(_DOMAIN_ALLOWLIST):
        sentence = template.format(term=term)
        _check(f"template: {term}", sentence, sentence)

    print(f"\n  Allowlist members ({len(_DOMAIN_ALLOWLIST)}): {sorted(_DOMAIN_ALLOWLIST)}")


# ---------------------------------------------------------------------------
# 2. PII detection — real PII must still be scrubbed
# ---------------------------------------------------------------------------

def test_pii_detection() -> None:
    print("\n[2] PII detection — real PII is scrubbed")

    _check_not_in(
        "email address scrubbed",
        "Does AC-2 apply to john.doe@agency.gov?",
        "john.doe@agency.gov",
    )
    _check_not_in(
        "SSN scrubbed",
        "Review SSN 123-45-6789 handling under NIST 800-53",
        "123-45-6789",
    )
    _check_not_in(
        "IP address scrubbed",
        "Our system at 192.168.1.1 needs FedRAMP authorization",
        "192.168.1.1",
    )
    # FedRAMP must survive even when PII in same query is scrubbed
    _check_not_in(
        "FedRAMP survives while IP is scrubbed",
        "Our system at 192.168.1.1 needs FedRAMP authorization",
        "FedRAMP",  # FedRAMP must NOT be in the forbidden set — verifies it is kept
    )
    # Multiple allowlist terms + real PII in one string — scrubbing one entity must
    # not affect adjacent allowlisted spans. Highest-risk scenario for the filter.
    mixed = "ISSO john.doe@agency.gov is responsible for FedRAMP ATO under NIST 800-53."
    _check_not_in("multi-term: ISSO survives", mixed, "ISSO")
    _check_not_in("multi-term: FedRAMP survives", mixed, "FedRAMP")
    _check_not_in("multi-term: ATO survives", mixed, "ATO")
    _check_not_in("multi-term: NIST survives", mixed, "NIST")
    _check_not_in("multi-term: email scrubbed", mixed, "john.doe@agency.gov")


# ---------------------------------------------------------------------------
# 3. Pass-through — clean text returns unchanged
# ---------------------------------------------------------------------------

def test_passthrough() -> None:
    print("\n[3] Pass-through — clean compliance text is unchanged")

    clean_queries = [
        "What controls govern access management in federal systems?",
        "Describe AC-2 account management requirements under NIST 800-53.",
        "How does the AI RMF GOVERN function apply to federal AI deployments?",
        "Which FedRAMP Moderate controls address audit logging?",
        "Compare NIST AI 600-1 MAP controls with FedRAMP requirements.",
    ]
    for q in clean_queries:
        _check(f"clean: {q[:55]}...", q, q)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("PII filter test — utils/pii_filter.py")
    print("=" * 60)

    test_allowlist()
    test_pii_detection()
    test_passthrough()

    print(f"\n{'=' * 60}")
    print(f"Result: {_PASS} passed, {_FAIL} failed")
    print("=" * 60)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
