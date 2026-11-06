"""Upload file registry columns and upl_ id (task 1)."""

from __future__ import annotations

import sqlalchemy as sa

from oa_agent.db.models import ExportFile
from oa_agent.ids import new_export_file_id, new_upload_file_id


def test_upload_file_id_prefix():
    assert new_upload_file_id().startswith("upl_")


def test_export_row_defaults_remain_export(installed):
    rt = installed.app.state.runtime
    file_id = new_export_file_id()
    with rt.session() as session, session.begin():
        row = ExportFile(
            file_id=file_id,
            tenant_id="dscpa",
            ticket="ticket_export_default_01",
            oa="a",
            filename="a.txt",
            size_bytes=1,
            content_type="text/plain",
            storage="local",
            object_key="dscpa/ticket_export_default_01.bin",
        )
        session.add(row)

    with rt.session() as session:
        row = session.execute(sa.select(ExportFile).where(ExportFile.file_id == file_id)).scalar_one()
        assert row.origin == "export"
        assert row.in_message is True
        assert row.sha256 is None
