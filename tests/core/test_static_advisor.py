"""
tests/core/test_static_advisor.py
===================================
Unit tests for the framework-agnostic Static AST Advisor.
Marker: `core` (no DB, no Django, pure Python only).

API: StaticASTAdvisor(source_code).run() -> List[Dict]
Finding types: ORM_CALL_IN_LOOP, BLOCKING_EXTERNAL_CALL
"""
import textwrap
from dqs.core.static_advisor import StaticASTAdvisor


def test_detects_orm_call_in_loop():
    """ORM queryset calls inside a for-loop body must be flagged as ORM_CALL_IN_LOOP."""
    code = textwrap.dedent("""
        def process_users(users):
            for user in users:
                profile = user.profile.get()
                print(profile)
    """)
    findings = StaticASTAdvisor(code).run()
    loop_findings = [f for f in findings if f["type"] == "ORM_CALL_IN_LOOP"]
    assert len(loop_findings) >= 1
    assert loop_findings[0]["line"] == 4


def test_detects_aliased_blocking_call():
    """Blocking callables accessed via import aliases must still be detected as BLOCKING_EXTERNAL_CALL."""
    code = textwrap.dedent("""
        import requests as r
        from time import sleep as snooze

        def fetch_data():
            snooze(1)
            response = r.post("https://api.example.com")
    """)
    findings = StaticASTAdvisor(code).run()
    blocking = [f for f in findings if f["type"] == "BLOCKING_EXTERNAL_CALL"]
    targets = [f.get("message", "") for f in blocking]
    assert len(blocking) == 2
    assert any("time.sleep" in t for t in targets)
    assert any("requests.post" in t for t in targets)


def test_ignores_safe_code():
    """A function with no ORM calls or blocking I/O must produce zero findings."""
    code = textwrap.dedent("""
        def safe_function():
            data = [1, 2, 3]
            for item in data:
                print(item)
    """)
    findings = StaticASTAdvisor(code).run()
    assert len(findings) == 0


def test_detects_orm_filter_in_while_loop():
    """ORM calls inside while-loops must also be flagged as ORM_CALL_IN_LOOP."""
    code = textwrap.dedent("""
        def poll_status():
            while True:
                result = MyModel.objects.filter(status="pending")
    """)
    findings = StaticASTAdvisor(code).run()
    loop_findings = [f for f in findings if f["type"] == "ORM_CALL_IN_LOOP"]
    assert len(loop_findings) >= 1