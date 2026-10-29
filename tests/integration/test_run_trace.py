HEADERS = {"X-Tenant-Id": "t1", "X-User-Id": "u1", "X-Roles": "admin"}


async def _run_with_steps(db_session, *, conversation_id: int, run_id: str = "run_trace", tenant_id: str = "t1") -> None:
    from app.domain.session.models import Run, RunStep

    db_session.add(
        Run(
            id=run_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            trace_id="trace_1",
            agent_code="district_consult",
            status="COMPLETED",
            current_step=2,
            tool_call_count=1,
            token_input=100,
            token_output=50,
        )
    )
    db_session.add_all(
        [
            RunStep(
                tenant_id=tenant_id,
                run_id=run_id,
                step_no=1,
                step_type="MODEL_RESPONSE",
                status="SUCCESS",
                output_summary="决策：调用工具",
            ),
            RunStep(
                tenant_id=tenant_id,
                run_id=run_id,
                step_no=2,
                step_type="TOOL_RESULT",
                status="SUCCESS",
                tool_code="knowledge.search",
                output_summary="命中 2 条",
            ),
        ]
    )
    await db_session.commit()


async def test_run_trace_returns_steps(async_client, db_session) -> None:
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    await _run_with_steps(db_session, conversation_id=int(session_id))

    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/runs/run_trace", headers=HEADERS
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["run"]["status"] == "COMPLETED"
    assert data["run"]["usage"] == {"input": 100, "output": 50}
    assert [step["stepType"] for step in data["steps"]] == ["MODEL_RESPONSE", "TOOL_RESULT"]


async def test_run_trace_is_tenant_isolated(async_client, db_session) -> None:
    session_id = (
        await async_client.post("/api/v1/chat/sessions", json={"channel": "web"}, headers=HEADERS)
    ).json()["data"]["sessionId"]
    await _run_with_steps(db_session, conversation_id=int(session_id), tenant_id="t2")

    response = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}/runs/run_trace", headers=HEADERS
    )

    assert response.status_code == 404


async def test_submit_feedback(async_client) -> None:
    response = await async_client.post(
        "/api/v1/feedback",
        json={"rating": "down", "reason": "answer_inaccurate", "comment": "政策不一致"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["rating"] == "down"


async def test_feedback_rejects_unknown_rating(async_client) -> None:
    response = await async_client.post("/api/v1/feedback", json={"rating": "great"}, headers=HEADERS)

    assert response.status_code == 422
