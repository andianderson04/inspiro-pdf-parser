import os
import re
import base64
import pdfplumber
import requests
from flask import Flask, request, jsonify
from io import BytesIO

app = Flask(__name__)

SUPABASE_URL = "https://kjtohbkajcscayckyypi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtqdG9oYmthamNzY2F5Y2t5eXBpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA5OTkzMTgsImV4cCI6MjA5NjU3NTMxOH0.VzKnzpf4VFi06kn28Wz_b8kcWwujF7d5lQG0Xwa6aiw"

PDF_PASSWORDS = ["0812", "9891"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def decode_pdf(raw_body):
    """Handle both raw binary and base64-encoded PDF from Power Automate."""
    if isinstance(raw_body, bytes):
        try:
            decoded = base64.b64decode(raw_body)
            if decoded[:4] == b'%PDF':
                return decoded
        except Exception:
            pass
        if raw_body[:4] == b'%PDF':
            return raw_body
        try:
            text = raw_body.decode('utf-8').strip().strip('"')
            decoded = base64.b64decode(text)
            if decoded[:4] == b'%PDF':
                return decoded
        except Exception:
            pass
    return raw_body

def open_pdf(pdf_bytes):
    """Try opening PDF with known passwords, fall back to no password."""
    for pwd in PDF_PASSWORDS:
        try:
            return pdfplumber.open(BytesIO(pdf_bytes), password=pwd)
        except Exception:
            continue
    try:
        return pdfplumber.open(BytesIO(pdf_bytes))
    except Exception as e:
        raise Exception(f"Could not open PDF with any known password: {str(e)}")

def detect_company(source_file, full_text=""):
    """Detect company from source filename/subject or PDF text."""
    combined = (source_file + " " + full_text).upper()
    if "INFOCOM" in combined:
        return "Infocom"
    if "INSPIRO" in combined:
        return "Inspiro"
    return "Inspiro"  # default

def extract_approved_date(full_text):
    """
    Extract the approval date from text like:
    'Successful Payroll Accounts Opened on 06/10/2026 - 06/11/2026 via Digital Payroll Portal'
    Returns the LAST (end) date in MM/DD/YYYY -> YYYY-MM-DD format.
    """
    pattern = r"Opened on\s+(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})"
    match = re.search(pattern, full_text, re.IGNORECASE)
    if match:
        end_date = match.group(2)
        try:
            mm, dd, yyyy = end_date.split("/")
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        except Exception:
            return end_date
    # Fallback: any single date pattern "Opened on MM/DD/YYYY"
    pattern2 = r"Opened on\s+(\d{1,2}/\d{1,2}/\d{4})"
    match2 = re.search(pattern2, full_text, re.IGNORECASE)
    if match2:
        d = match2.group(1)
        try:
            mm, dd, yyyy = d.split("/")
            return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        except Exception:
            return d
    return ""

def normalize_reason(r):
    r = r.strip().upper()
    if "NO HR" in r or "KYC" in r:
        return "No HR/KYC Certification"
    if "MOBILE" in r:
        return "Mismatch: Mobile Number"
    if "BIRTH" in r or "DOB" in r:
        return "Mismatch: Date of Birth"
    if "MATCHED" in r:
        return "HR Cert. Already Matched"
    return r.title()

def parse_pending(pdf_bytes, source_file):
    records = []
    with open_pdf(pdf_bytes) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        company = detect_company(source_file, full_text)

        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                try:
                    no = int(str(row[0]).strip())
                except Exception:
                    continue

                first    = str(row[1] or "").strip()
                middle   = str(row[2] or "").strip()
                last     = str(row[3] or "").strip()
                suffix   = str(row[4] or "").strip()
                app_date = str(row[5] or "").strip()
                dob      = str(row[6] or "").strip()
                mobile   = str(row[7] or "").strip()
                reason   = str(row[8] or "").strip()

                parts = [p for p in [first, middle, last, suffix] if p]
                full_name = " ".join(parts)

                if app_date and " " in app_date:
                    app_date = app_date.split(" ")[0]

                records.append({
                    "row_no": no,
                    "full_name": full_name,
                    "date_of_birth": dob,
                    "application_date": app_date,
                    "mobile_number": mobile,
                    "reason": normalize_reason(reason) if reason else "",
                    "source_file": source_file,
                    "company": company
                })
    return records

def parse_approved(pdf_bytes, source_file, fallback_date=""):
    records = []
    with open_pdf(pdf_bytes) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        company = detect_company(source_file, full_text)
        date_approved = extract_approved_date(full_text) or fallback_date

        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                try:
                    no = int(str(row[0]).strip())
                except Exception:
                    continue

                first   = str(row[1] or "").strip()
                middle  = str(row[2] or "").strip()
                last    = str(row[3] or "").strip()
                suffix  = str(row[4] or "").strip()
                account = str(row[5] or "").strip()
                branch  = str(row[6] or "").strip()

                parts = [p for p in [first, middle, last, suffix] if p]
                full_name = " ".join(parts)

                records.append({
                    "row_no": no,
                    "full_name": full_name,
                    "account_number": account,
                    "rcbc_branch": branch,
                    "date_approved": date_approved,
                    "source_file": source_file,
                    "company": company
                })
    return records

def save_to_supabase(table, records):
    if not records:
        return {"saved": 0, "message": "No records parsed"}
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=HEADERS,
        json=records
    )
    return {"saved": len(records), "status": res.status_code, "response": res.text}

@app.route("/parse-pending", methods=["POST"])
def handle_pending():
    try:
        raw = request.data
        pdf_bytes = decode_pdf(raw)
        source_file = request.headers.get("X-Source-File", "unknown")
        records = parse_pending(pdf_bytes, source_file)
        result = save_to_supabase("pending", records)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/parse-approved", methods=["POST"])
def handle_approved():
    try:
        raw = request.data
        pdf_bytes = decode_pdf(raw)
        source_file = request.headers.get("X-Source-File", "unknown")
        fallback_date = request.headers.get("X-Date-Approved", "")
        records = parse_approved(pdf_bytes, source_file, fallback_date)
        result = save_to_supabase("approved", records)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
