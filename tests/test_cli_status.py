from vc import format_health_summary


def test_cli_health_summary_reports_degraded_provider_and_agentmemory_state():
    text = format_health_summary(
        {
            "status": "degraded",
            "version": "2.3.0",
            "models": 6,
            "providers": [
                {"ready": True, "name": "Opus"},
                {"ready": False, "name": "DeepSeek", "missing": ["api_key"]},
            ],
            "agentmemory": {"ready": False, "status": "unreachable"},
            "warnings": ["One or more providers are missing runtime configuration."],
        }
    )

    assert "degraded" in text
    assert "Providers 1/2 ready" in text
    assert "agentmemory unreachable" in text
    assert "api_key" not in text
