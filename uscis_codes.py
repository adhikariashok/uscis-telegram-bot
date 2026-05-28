# USCIS event/action code → human-readable label
#
# Sources:
#   - NIEM 5.0 SCR domain: BenefitDocumentStatusCategoryCodeSimpleType
#     https://niem.github.io/model/5.0/scr/BenefitDocumentStatusCategoryCodeSimpleType/
#   - USCIS case status community documentation
#
# Used as a fallback when the API returns a bare code in eventCode/actionType
# without a description/title alongside it.

EVENT_CODES: dict[str, str] = {
    # ── Core case decisions ───────────────────────────────────────────────────
    "APVL": "Approval",
    "APVD": "Approved",
    "DENY": "Denied / Denial",
    "WTHD": "Withdrawn",
    "WTDN": "Withdrawn",
    "TERM": "Terminated",
    "TRMD": "Terminated",
    "ABAN": "Abandoned",
    "CLOS": "Case Closed",
    "REOP": "Case Reopened",
    "EXPD": "Expired",
    "SUSP": "Suspended",
    "RJCT": "Rejected",
    "REJT": "Rejected",

    # ── Receipt & intake ──────────────────────────────────────────────────────
    "RCPT": "Case Received",
    "INIT": "Initial Receipt",
    "APPL": "Application Filed",
    "FEES": "Fee Received",
    "FNGP": "Fingerprint Fee Received",

    # ── Processing stages ─────────────────────────────────────────────────────
    "PEND": "Pending",
    "ACTV": "Active / In Progress",
    "RVWG": "Under Review",
    "COMP": "Case Complete",
    "HOLD": "On Hold",
    "DECN": "Decision Made",

    # ── RFE / evidence ────────────────────────────────────────────────────────
    "RFEI": "Request for Evidence Issued",
    "RESP": "Response to RFE Received",
    "NOID": "Notice of Intent to Deny",
    "NOIT": "Notice of Intent to Terminate",

    # ── Biometrics ────────────────────────────────────────────────────────────
    "BFBI": "Biometrics Appointment",
    "BFBC": "Biometrics Completed",
    "BFBS": "Biometrics Scheduled",

    # ── Interview ─────────────────────────────────────────────────────────────
    "INTP": "Interview",
    "INTW": "Interview Scheduled",
    "INTC": "Interview Completed",
    "INTS": "Interview Scheduled",

    # ── Notices & mail ────────────────────────────────────────────────────────
    "NTCO": "Notice / Correspondence Sent",
    "NTCE": "Notice Mailed",
    "MAIL": "Mail Sent",
    "SCHD": "Scheduled",
    "APPT": "Appointment",

    # ── Card production ───────────────────────────────────────────────────────
    "CARD": "Card Ordered / Produced",
    "PROD": "Card Production Ordered",
    "DELI": "Card Delivered",
    "CDML": "Card Mailed",

    # ── Transfer ──────────────────────────────────────────────────────────────
    "XFER": "Transferred to New Office",
    "TRNS": "Transfer",

    # ── Appeals / motions ─────────────────────────────────────────────────────
    "MTRO": "Motion to Reopen",
    "MTRN": "Motion to Reconsider",
    "APEL": "Appeal Filed",
    "AAPC": "Appeal Accepted",
    "AAPD": "Appeal Denied",

    # ── Miscellaneous ─────────────────────────────────────────────────────────
    "UPDT": "Updated",
    "CANC": "Cancelled",
    "EXTN": "Extension",
    "AMND": "Amendment",
    "SUPP": "Supplement",
}
