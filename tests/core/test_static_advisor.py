import textwrap
from dqs.core.static_advisor import StaticASTAdvisor

def test_detects_orm_call_in_loop():
    code = textwrap.dedent("""
        def process_users(users):
            for user in users:
                # This should flag as ORM_CALL_IN_LOOP
                profile = user.profile.get()
                print(profile)
    """)
    advisor = StaticASTAdvisor(code)
    findings = advisor.analyze()
    
    assert len(findings) == 1
    assert findings[0]["type"] == "ORM_CALL_IN_LOOP"
    assert findings[0]["line"] == 4

def test_detects_aliased_blocking_call():
    code = textwrap.dedent("""
        import requests as r
        from time import sleep as snooze

        def fetch_data():
            # Both of these should be caught despite the aliasing
            snooze(1)
            response = r.post("https://api.example.com")
    """)
    advisor = StaticASTAdvisor(code)
    findings = advisor.analyze()
    
    blocking_targets = [f["target"] for f in findings if f["type"] == "BLOCKING_CALL"]
    assert len(blocking_targets) == 2
    assert "time.sleep" in blocking_targets
    assert "requests.post" in blocking_targets

def test_ignores_safe_code():
    code = textwrap.dedent("""
        def safe_function():
            data = [1, 2, 3]
            for item in data:
                print(item)
    """)
    advisor = StaticASTAdvisor(code)
    findings = advisor.analyze()
    
    assert len(findings) == 0