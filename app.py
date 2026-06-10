import os
import re
import pdfplumber
import requests
from flask import Flask, request, jsonify
from io import BytesIO

app = Flask(__name__)

SUPABASE_URL = "https://kjtohbkajcscayckyypi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtqdG9oYmthamNzY2F5Y2t5eXBpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA5OTkzMTgsImV4cCI6MjA5NjU3NTMxOH0.VzKnzpf4VFi06kn28Wz_b8kcWwujF7d5lQG0Xwa6aiw"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

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
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                try:
                    no = int(str(row[0]).strip())
                except:
                    continue
                first   = str(row[1] or "").strip()
                middle  = str(row[2] or "").strip()
                last    = str(row[3] or "").strip()
                suffix  = str(row[4] or "").strip()
                app_date= str(row[5] or "").strip()
                dob     = str(row[6] or "").strip()
                mobile  = str(row[7] or "").strip()
                reason  = str(row[8] or "").strip()

                parts = [first, middle, last]
                if suffix:
                    parts.append(suffix)
                full_name = " ".join(p for p in parts if p)

                records.append({
                    "row_no": no,
                    "full_name": full_name,
                    "date_of_birth": dob,
                    "application_date": app_date,
                    "mobile_number": mobile,
                    "reason": normalize_reason(reason),
                    "source_file": source_file
                })
    return records

def parse_approved(pdf_bytes, source_file, date_approved):
    records = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or not row[0]:
                    continue
                try:
                    no = int(str(row[0]).strip())
                except:
                    continue
                first   = str(row[1] or "").strip()
                middle  = str(row[2] or "").strip()
                last    = str(row[3] or "").strip()
                suffix  = str(row[4] or "").strip()
                account = str(row[5] or "").strip()
                branch  = str(row[6] or "").strip()

                parts = [first, middle, last]
                if suffix:
                    parts.append(suffix)
                full_name = " ".join(p for p in parts if p)

                records.append({
                    "row_no": no,
                    "full_name": full_name,
                    "account_number": account,
                    "rcbc_branch": branch,
                    "date_approved": date_approved,
                    "source_file": source_file
                })
    return records

def save_to_supabase(table, records):
    if not records:
        return {"saved": 0}
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=HEADERS,
        json=records
    )
    return {"saved": len(records), "status": res.status_code}

@app.route("/parse-pending", methods=["POST"])
def handle_pending():
    pdf_bytes   = request.data
    source_file = request.headers.get("X-Source-File", "unknown")
    records     = parse_pending(pdf_bytes, source_file)
    result      = save_to_supabase("pending", records)
    return jsonify(result)

@app.route("/parse-approved", methods=["POST"])
def handle_approved():
    pdf_bytes    = request.data
    source_file  = request.headers.get("X-Source-File", "unknown")
    date_approved= request.headers.get("X-Date-Approved", "")
    records      = parse_approved(pdf_bytes, source_file, date_approved)
    result       = save_to_supabase("approved", records)
    return jsonify(result)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
