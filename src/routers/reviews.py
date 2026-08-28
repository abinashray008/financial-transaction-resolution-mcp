"""Authenticated back-office review application for persisted dispute cases.

These HTTP routes are not MCP tools. FastMCP's Descope middleware wraps ``/mcp``
only, so both ``GET /reviews/{case_id}`` and ``POST /reviews/{case_id}/decision``
authenticate here. A reviewer must present a verified JWT with the review scope;
identity is taken from the ``sub`` claim. Form and ``X-Reviewer-Id`` values are
accepted only in ``local-demo`` mode. ``reviewer_id`` is never read from JSON.
"""

from __future__ import annotations

import html
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from ..app.container import Container
from ..app.presenters import to_dispute_case_view, to_review_decision
from ..app.validators import (
    validate_case_id,
    validate_case_version,
    validate_review_decision,
    validate_review_note,
    validate_review_reason_code,
)
from ..contracts.requests import ReviewDecisionRequest
from ..domain.enums import REJECT_REASON_CODES, ReviewDecision, ReviewReasonCode
from ..domain.exceptions import DomainError, ErrorCode, InvalidInputError
from ..security.reviewer import ReviewAuth, ReviewAuthError, authenticate_reviewer, reviewer_id_from_request

_PAGE_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;"
    "line-height:1.5;color:#111}"
    "code{background:#f4f4f4;padding:0.1rem 0.3rem}"
    "dl{display:grid;grid-template-columns:12rem 1fr;gap:0.35rem 1rem}"
    "dt{color:#555}"
    "form{margin-top:1.5rem;display:flex;flex-direction:column;gap:0.75rem}"
    "textarea,input,select{font:inherit;padding:0.35rem}"
    "button{font:inherit;padding:0.4rem 0.8rem;margin-right:0.5rem}"
)

_HTTP_STATUS = {
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.DISPUTE_WORKFLOW_NOT_FOUND: 404,
    ErrorCode.DISPUTE_CASE_NOT_FOUND: 404,
    ErrorCode.DISPUTE_NOT_AWAITING_REVIEW: 409,
    ErrorCode.DISPUTE_ALREADY_EXISTS: 409,
    ErrorCode.DISPUTE_CASE_VERSION_CONFLICT: 409,
    ErrorCode.DISPUTE_REVIEW_ALREADY_RECORDED: 409,
}


def register_review_routes(mcp: FastMCP, container: Container, *, review_auth: ReviewAuth) -> None:
    """Expose ``GET /reviews/{case_id}`` and ``POST /reviews/{case_id}/decision``."""

    @mcp.custom_route("/reviews/{case_id}", methods=["GET"], name="review_case")
    async def review_case(request: Request) -> Response:
        try:
            reviewer_id = await authenticate_reviewer(
                request,
                review_auth,
                require_identity=not review_auth.is_local_demo,
            )
            case_id = validate_case_id(request.path_params["case_id"])
            case = container.cases.get_for_review(
                case_id,
                reviewer_id=reviewer_id,
                correlation_id=case_id,
            )
            snapshot = container.disputes.get_snapshot(case_id)
            history = container.lifecycle.case_history(case_id)
        except ReviewAuthError as error:
            return _auth_error_response(request, error)
        except DomainError as error:
            return _error_response(request, error)

        data = to_dispute_case_view(case, snapshot, history)
        if _wants_html(request):
            return HTMLResponse(
                _case_html(
                    data.model_dump(mode="json"),
                    case_id=case_id,
                    review_auth=review_auth,
                    reviewer_id=reviewer_id,
                )
            )
        return JSONResponse(data.model_dump(mode="json"))

    @mcp.custom_route("/reviews/{case_id}/decision", methods=["POST"], name="record_review_decision")
    async def record_review_decision(request: Request) -> Response:
        try:
            payload = await _decision_payload(request)
            if request.headers.get("content-type", "").startswith("application/json") and "reviewer_id" in payload:
                raise InvalidInputError("reviewer_id is not accepted in the decision body.")
            raw_reviewer = payload.get("reviewer_id") if review_auth.is_local_demo else None
            reviewer_id = await reviewer_id_from_request(
                request,
                review_auth,
                form_reviewer_id=raw_reviewer if isinstance(raw_reviewer, str) else None,
            )
            path_case_id = validate_case_id(request.path_params["case_id"])
            decision_request = _review_decision_request(payload, path_case_id=path_case_id)
            decision = validate_review_decision(decision_request.decision)
            reason_code = validate_review_reason_code(decision_request.reason_code, decision=decision)
            note = validate_review_note(decision_request.note)
            updated = container.cases.record_review(
                case_id=path_case_id,
                expected_version=decision_request.expected_version,
                decision=decision,
                reason_code=reason_code,
                note=note,
                reviewer_id=reviewer_id,
                correlation_id=path_case_id,
            )
        except ReviewAuthError as error:
            return _auth_error_response(request, error)
        except DomainError as error:
            return _error_response(request, error)

        body = to_review_decision(updated).model_dump(mode="json")
        if _wants_html(request):
            return HTMLResponse(_decided_html(body), status_code=200)
        return JSONResponse(body, status_code=200)


def _is_browser_form(request: Request) -> bool:
    content_type = request.headers.get("content-type", "")
    return "application/x-www-form-urlencoded" in content_type


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    if "application/json" in accept.split(",")[0]:
        return False
    if _is_browser_form(request):
        return True
    return "text/html" in accept


async def _decision_payload(request: Request) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise InvalidInputError("The decision body must be a JSON object.")
        return raw
    form = await request.form()
    return {key: str(value) for key, value in form.items() if isinstance(value, str)}


def _review_decision_request(payload: dict[str, object], *, path_case_id: str) -> ReviewDecisionRequest:
    body = dict(payload)
    body.pop("reviewer_id", None)
    if "case_id" not in body:
        body["case_id"] = path_case_id
    if "note" not in body and "decision_note" in body:
        body["note"] = body.pop("decision_note")
    try:
        case_id = validate_case_id(str(body.get("case_id") or path_case_id))
        request = ReviewDecisionRequest.model_validate(
            {
                "case_id": case_id,
                "expected_version": validate_case_version(body.get("expected_version")),
                "decision": body.get("decision"),
                "reason_code": body.get("reason_code"),
                "note": body.get("note"),
            }
        )
    except InvalidInputError:
        raise
    except Exception as error:
        raise InvalidInputError(
            "The decision body must include case_id, expected_version, decision and reason_code."
        ) from error
    if request.case_id != path_case_id:
        raise InvalidInputError("case_id in the body must match the URL.")
    return request


def _auth_error_response(request: Request, error: ReviewAuthError) -> Response:
    payload = {"error": {"code": error.code, "message": error.message}}
    headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
    if _wants_html(request):
        message = html.escape(error.message)
        heading = "Cannot record this decision" if request.method == "POST" else "Cannot view this review"
        return HTMLResponse(
            f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Review error</title>"
            f"<style>{_PAGE_STYLE}</style></head><body><h1>{heading}</h1>"
            f"<p>{message}</p></body></html>",
            status_code=error.status_code,
            headers=headers,
        )
    return JSONResponse(payload, status_code=error.status_code, headers=headers)


def _error_response(request: Request, error: DomainError) -> Response:
    status = _HTTP_STATUS.get(error.code, 500)
    payload = {"error": {"code": error.code.value, "message": error.safe_message}}
    if _wants_html(request):
        message = html.escape(error.safe_message)
        return HTMLResponse(
            f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Review error</title>"
            f"<style>{_PAGE_STYLE}</style></head><body><h1>Cannot record this decision</h1>"
            f"<p>{message}</p></body></html>",
            status_code=status,
        )
    return JSONResponse(payload, status_code=status)


def _case_html(
    data: dict[str, Any],
    *,
    case_id: str,
    review_auth: ReviewAuth,
    reviewer_id: str | None,
) -> str:
    escaped_case_id = html.escape(case_id)
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"
        for label, value in (
            ("Case", str(data["case_id"])),
            ("Status", str(data["status"])),
            ("Version", str(data["version"])),
            ("Transaction", str(data["transaction_id"])),
            ("Merchant", str(data["merchant_display_name"])),
            ("Amount", f"{data['amount']} {data['currency']}"),
            ("Reason code", str(data["reason_code"])),
            ("Policy", str(data["applied_policy"])),
            ("Proposed action", str(data["proposed_action"])),
            ("Evidence hash", str(data["evidence_hash"])),
            ("Verified evidence", "; ".join(data["verified_evidence"]) or "None"),
            ("Missing evidence", "; ".join(data["missing_evidence"]) or "None"),
        )
    )
    reason_options = "".join(
        f"<option value='{html.escape(code.value)}'>{html.escape(code.value)}</option>" for code in ReviewReasonCode
    )
    if review_auth.is_local_demo:
        reviewer_field = (
            "<label>Reviewer id <input name='reviewer_id' required "
            "pattern='[A-Za-z0-9_.:@|-]{1,128}' value='local-reviewer'></label>"
        )
        auth_note = (
            "<p><strong>Local demo mode.</strong> This form accepts a reviewer id "
            "that is not authenticated. Do not use this outside a local demo.</p>"
        )
        form = (
            f"<form method='post' action='/reviews/{escaped_case_id}/decision'>"
            f"<input type='hidden' name='case_id' value='{escaped_case_id}'>"
            f"<input type='hidden' name='expected_version' value='{html.escape(str(data['version']))}'>"
            "<label>Decision <select name='decision' required>"
            f"<option value='{ReviewDecision.APPROVE.value}'>Approve</option>"
            f"<option value='{ReviewDecision.REJECT.value}'>Reject</option>"
            "</select></label>"
            f"<label>Reason code <select name='reason_code' required>{reason_options}</select></label>"
            "<label>Note <textarea name='note' rows='3' maxlength='500'></textarea></label>"
            f"{reviewer_field}"
            "<div><button type='submit'>Record decision</button></div>"
            "</form>"
        )
    else:
        signed_in = html.escape(reviewer_id or "")
        auth_note = (
            f"<p>Authenticated as <code>{signed_in}</code>. Record a decision with "
            "<code>Authorization: Bearer …</code> and a JSON body. The token must "
            f"include the <code>{html.escape(review_auth.required_scope)}</code> scope or role. "
            "A browser form cannot send that token, so this page does not submit a decision.</p>"
        )
        form = ""
    reason = html.escape(str(data["reason"]))
    reject_hint = ", ".join(code.value for code in sorted(REJECT_REASON_CODES, key=lambda item: item.value))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Review dispute case</title><style>{_PAGE_STYLE}</style></head><body>"
        "<h1>Review dispute case</h1>"
        "<p>This internal case is already persisted at <code>PENDING_REVIEW</code>. "
        "Approve or reject it here. Nothing is submitted to an issuer or card network.</p>"
        f"{auth_note}"
        f"<dl>{rows}</dl>"
        f"<p><strong>Reason</strong></p><p>{reason}</p>"
        f"<p>Reject reason codes include: {html.escape(reject_hint)}.</p>"
        f"{form}</body></html>"
    )


def _decided_html(data: dict[str, Any]) -> str:
    case_id = html.escape(str(data["case_id"]))
    status = html.escape(str(data["status"]))
    reason_code = html.escape(str(data["reason_code"]))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Decision recorded</title><style>{_PAGE_STYLE}</style></head><body>"
        "<h1>Decision recorded</h1>"
        f"<p>Case <code>{case_id}</code> is now <code>{status}</code> "
        f"(<code>{reason_code}</code>).</p>"
        "<p>This is an internal synthetic case file. It was not submitted externally.</p>"
        "</body></html>"
    )
