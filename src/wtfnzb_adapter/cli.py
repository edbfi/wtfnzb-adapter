from wtfnzb_adapter.session import environment


def main() -> None:
    # This command acquires the same instance lock and budget as the service via
    # the shared scheduler; bootstrap reserves browser actions without HTTP calls.
    import asyncio

    from wtfnzb_adapter.session_budget import capture_with_budget

    success = asyncio.run(capture_with_budget(environment()))
    print(
        "Session captured"
        if success
        else "Session refresh failed; inspect Ego and .state/login-blocked"
    )
    if not success:
        raise SystemExit(1)
