"""Human review application for dispute drafts.

These HTTP routes are not MCP tools. FastMCP's Descope middleware wraps ``/mcp``
only, so both ``GET /reviews/{request_id}`` and
``POST /reviews/{request_id}/decision`` authenticate here. A reviewer must
present a verified JWT with the review scope; identity is taken from the
``sub`` claim. Form and ``X-Reviewer-Id`` values are accepted only in
``local-demo`` mode.
"""

from __future__ import annotations

import html
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from ..app.container import Container
from ..app.presenters import to_approval_record, to_dispute_draft
from ..app.validators import validate_decision_note, validate_request_id
from ..domain.enums import ApprovalDecision
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
    ErrorCode.DISPUTE_NOT_AWAITING_APPROVAL: 409,
    ErrorCode.DISPUTE_ALREADY_EXISTS: 409,
    ErrorCode.DISPUTE_APPROVAL_NOT_FOUND: 404,
    ErrorCode.DISPUTE_APPROVAL_EXPIRED: 409,
    ErrorCode.DISPUTE_APPROVAL_ALREADY_CONSUMED: 409,
    ErrorCode.DISPUTE_APPROVAL_MISMATCH: 409,
}


def register_review_routes(mcp: FastMCP, container: Container, *, review_auth: ReviewAuth) -> None:
    """Expose ``GET /reviews/{request_id}`` and ``POST /reviews/{request_id}/decision``."""

    @mcp.custom_route("/reviews/{request_id}", methods=["GET"], name="review_proposal")
    async def review_proposal(request: Request) -> Response:
        try:
            reviewer_id = await authenticate_reviewer(
                request,
                review_auth,
                require_identity=not review_auth.is_local_demo,
            )
            request_id = validate_request_id(request.path_params["request_id"])
            proposal = container.dispute_workflow.get_pending(request_id)
        except ReviewAuthError as error:
            return _auth_error_response(request, error)
        except DomainError as error:
            return _error_response(request, error)

        data = to_dispute_draft(proposal)
        if _wants_html(request):
            return HTMLResponse(
                _proposal_html(
                    data.model_dump(mode="json"),
                    request_id=request_id,
                    review_auth=review_auth,
                    reviewer_id=reviewer_id,
                )
            )
        return JSONResponse(data.model_dump(mode="json"))

    @mcp.custom_route("/reviews/{request_id}/decision", methods=["POST"], name="record_review_decision")
    async def record_review_decision(request: Request) -> Response:
        try:
            payload = await _decision_payload(request)
            reviewer_id = await reviewer_id_from_request(
                request,
                review_auth,
                form_reviewer_id=payload.get("reviewer_id"),
            )
            request_id = validate_request_id(request.path_params["request_id"])
            decision = _parse_decision(payload.get("decision"))
            note = validate_decision_note(payload.get("decision_note"))
            record = container.approval_service.record_decision(
                request_id=request_id,
                reviewer_id=reviewer_id,
                decision=decision,
                decision_note=note,
            )
        except ReviewAuthError as error:
            return _auth_error_response(request, error)
        except DomainError as error:
            return _error_response(request, error)

        body = to_approval_record(record).model_dump(mode="json")
        if _wants_html(request):
            return HTMLResponse(_minted_html(body), status_code=201)
        return JSONResponse(body, status_code=201)


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


async def _decision_payload(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise InvalidInputError("The decision body must be a JSON object.")
        return {str(key): "" if value is None else str(value) for key, value in raw.items()}
    form = await request.form()
    return {key: str(value) for key, value in form.items() if isinstance(value, str)}


def _parse_decision(value: str | None) -> ApprovalDecision:
    candidate = (value or "").strip().lower()
    try:
        return ApprovalDecision(candidate)
    except ValueError as error:
        raise InvalidInputError("decision must be 'approved' or 'declined'.") from error


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


def _proposal_html(
    data: dict[str, Any],
    *,
    request_id: str,
    review_auth: ReviewAuth,
    reviewer_id: str | None,
) -> str:
    request_id = html.escape(request_id)
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"
        for label, value in (
            ("Transaction", str(data["transaction_id"])),
            ("Merchant", str(data["merchant_display_name"])),
            ("Amount", f"{data['amount']} {data['currency']}"),
            ("Date", str(data["transaction_date"])),
            ("Reason code", str(data["reason_code"])),
            ("Policy", str(data["applied_policy"])),
            ("Proposed action", str(data["proposed_action"])),
            ("Draft hash", str(data["draft_hash"])),
            ("Verified evidence", "; ".join(data["verified_evidence"]) or "None"),
            ("Missing evidence", "; ".join(data["missing_evidence"]) or "None"),
        )
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
            f"<form method='post' action='/reviews/{request_id}/decision'>"
            "<label>Decision <select name='decision' required>"
            "<option value='approved'>Approve</option>"
            "<option value='declined'>Decline</option>"
            "</select></label>"
            "<label>Note <textarea name='decision_note' rows='3' maxlength='500'></textarea></label>"
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
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Review dispute draft</title><style>{_PAGE_STYLE}</style></head><body>"
        "<h1>Review dispute draft</h1>"
        "<p>Record your decision here. The server will mint a one-time "
        "<code>approval_id</code>. Passing <code>approved=true</code> to the MCP tool is not enough.</p>"
        f"{auth_note}"
        f"<dl>{rows}</dl>"
        f"<p><strong>Reason</strong></p><p>{reason}</p>"
        f"{form}</body></html>"
    )


def _minted_html(data: dict[str, Any]) -> str:
    approval_id = html.escape(str(data["approval_id"]))
    request_id = html.escape(str(data["request_id"]))
    decision = html.escape(str(data["decision"]))
    expires = html.escape(str(data["expires_at"]))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Approval minted</title><style>{_PAGE_STYLE}</style></head><body>"
        "<h1>Decision recorded</h1>"
        f"<p>Decision: <code>{decision}</code></p>"
        f"<p>Give the host this one-time token for <code>submit_dispute_case</code>:</p>"
        f"<p><code>request_id</code>: {request_id}<br>"
        f"<code>approval_id</code>: {approval_id}</p>"
        f"<p>Expires at {expires}. It can be used once.</p>"
        "</body></html>"
    )
