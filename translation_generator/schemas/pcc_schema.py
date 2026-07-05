from __future__ import annotations

from pydantic import BaseModel, Field


class PCCSchema(BaseModel):
    doc_type: str = Field(default="pcc")
    cert_no: str = ""
    cert_date: str = ""
    name: str = ""
    relation_text: str = ""
    relation_text_es: str = ""
    father_name: str = ""
    passport_no: str = ""
    passport_issue_or_sentence_date: str = ""
    purpose: str = ""
    reference_no: str = ""
    sign_name: str = ""
    apostille_date: str = ""
    stamp_no: str = ""

