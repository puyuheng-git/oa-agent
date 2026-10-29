from datetime import timedelta

import sqlalchemy as sa

from oa_agent.db.models import ConversationMessage, ModelCallLog
from oa_agent.db.types import utcnow
from oa_agent.ids import new_message_id, new_model_call_id, new_run_id, new_thread_id
from oa_agent.observability.retention import purge_conversation_logs

import pytest

pytest_plugins = ("tests.test_chat",)


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def test_purge_conversation_logs_deletes_old_rows(rt):
    old = utcnow() - timedelta(days=40)
    run_id = new_run_id()
    thread_id = new_thread_id()
    with rt.session() as db, db.begin():
        db.add(
            ConversationMessage(
                message_id=new_message_id(),
                tenant_id=rt.tenant_id,
                thread_id=thread_id,
                run_id=run_id,
                oa="alice",
                role="user",
                content="old",
                created_at=old,
            )
        )
        db.add(
            ModelCallLog(
                call_id=new_model_call_id(),
                tenant_id=rt.tenant_id,
                run_id=run_id,
                thread_id=thread_id,
                oa="alice",
                messages_json=[],
                status="ok",
                created_at=old,
            )
        )
    with rt.session() as db, db.begin():
        counts = purge_conversation_logs(db, 30)
    assert counts["conversation_messages"] == 1
    assert counts["model_call_logs"] == 1
    with rt.session() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(ConversationMessage)) == 0
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCallLog)) == 0
