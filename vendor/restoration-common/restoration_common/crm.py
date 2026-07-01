#!/usr/bin/env python3
"""Vanguard CRM login and job-info scraping.

Shared by both the document generator and the photo report generator. Network
libraries (requests, bs4) are imported lazily so the rest of the toolkit loads
without them.
"""

import re
from pathlib import Path

from .paths import CRM_LOGIN_URL
from .credentials import load_crm_credentials

HASH_SALT = "5624aa37f80fa68cead207c291b5b2ccc29f141a5ac62dc05ed32a9e620e7275"
HASH_ITERATIONS = 100000
HASH_SIZE = 256


def crm_login(username: str, password: str):
    """Log into the Vanguard CRM (ONLYOFFICE/Teamlab Auth.aspx).

    Returns an authenticated requests.Session. Raises RuntimeError on failure.
    """
    import hashlib
    import binascii
    import requests
    from bs4 import BeautifulSoup

    salt_bytes = HASH_SALT.encode("utf-8")
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        HASH_ITERATIONS,
        dklen=HASH_SIZE // 8,
    )
    password_hash = binascii.hexlify(dk).decode("ascii")

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    resp = session.get(CRM_LOGIN_URL, timeout=15)
    soup = BeautifulSoup(resp.content, "html.parser")
    hidden_fields = {
        inp["name"]: inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }

    post_data = dict(hidden_fields)
    post_data["login"] = username
    post_data["passwordHash"] = password_hash
    # The ONLYOFFICE auth form also sends the plain password field; include it
    # so server-side validation that inspects #pwd does not reject the request.
    post_data["pwd"] = password

    resp = session.post(CRM_LOGIN_URL, data=post_data, timeout=15)

    if "auth" in resp.url.lower():
        raise RuntimeError("Login failed. Please check your username and password.")
    soup2 = BeautifulSoup(resp.content, "html.parser")
    if soup2.find("input", attrs={"name": "passwordHash"}):
        # Extract any visible error message from the response to aid diagnosis.
        error_text = ""
        for elem in soup2.find_all(["div", "span"]):
            txt = elem.get_text(strip=True)
            if txt and any(
                kw in txt.lower()
                for kw in ("invalid", "incorrect", "wrong", "failed", "error")
            ):
                error_text = txt
                break
        msg = "Login failed. Please check your username and password."
        if error_text:
            msg += f" CRM response: {error_text}"
        raise RuntimeError(msg)

    return session


def fetch_job_info_from_url(url: str) -> dict:
    """Fetch job fields from a Vanguard CRM deal page or a saved HTML file.

    Returns dict with keys: customer_name, claim_number, job_location, job_id,
    sales_rep.
    """
    import json as _json
    from bs4 import BeautifulSoup

    # Local saved HTML files need no login.
    if not url.startswith(("http://", "https://")):
        local_path = Path(url)
        if not local_path.exists():
            raise RuntimeError(f"File not found: {url}")
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            raise RuntimeError(f"Could not read file: {e}")
        soup = BeautifulSoup(content, "html.parser")
    else:
        username, password = load_crm_credentials()
        session = crm_login(username, password)

        response = session.get(url, timeout=15)
        if "auth" in response.url.lower():
            raise RuntimeError("Authentication expired. Please re-enter your credentials.")
        if response.status_code != 200:
            raise RuntimeError(f"Failed to load page (HTTP {response.status_code}).")

        soup = BeautifulSoup(response.content, "html.parser")

    name_span = soup.find("span", class_="crm-pageHeaderText text-overflow")
    customer_name = name_span.get_text(strip=True) if name_span else ""

    claim_number = ""
    job_location = ""
    sales_rep = ""
    crm_job_id = ""
    for script in soup.find_all("script"):
        text = script.string or ""
        m = re.search(r"var customFieldList\s*=\s*(\[.*?\]);", text, re.DOTALL)
        if m:
            try:
                fields = _json.loads(m.group(1))
                for field in fields:
                    label = field.get("label", "").strip().lower()
                    value = field.get("value", "").strip()
                    if label == "claim #":
                        claim_number = value
                    elif label == "address":
                        job_location = " ".join(value.split())
                    elif label == "contractor sales rep":
                        sales_rep = value
                    elif label in ("crm job/id", "crm job id", "crm job#", "job/id", "job id"):
                        crm_job_id = value
            except (ValueError, KeyError):
                pass
            break

    # Fallback: parse visible details table if script variable is missing.
    if not claim_number or not job_location or not sales_rep or not crm_job_id:
        table = soup.find("table", class_="crm-detailsTable")
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue
                label_cell = cells[0]
                label = (label_cell.get("title", "") or label_cell.get_text(strip=True)).lower().rstrip(":")
                value_cell = cells[2]
                value = " ".join(value_cell.get_text(strip=True).split())
                if not claim_number and label == "claim #":
                    claim_number = value
                if not job_location and label == "address":
                    job_location = value
                if not sales_rep and label == "contractor sales rep":
                    sales_rep = value
                if not crm_job_id and label in ("crm job/id", "crm job id", "crm job#", "job/id", "job id"):
                    crm_job_id = value

    job_id = crm_job_id
    if not job_id:
        page_text = soup.get_text()
        m = re.search(r"([A-Z]{2})\s*-?\s*(\d{5})", page_text)
        if m:
            job_id = f"{m.group(1)}-{m.group(2)}"
        else:
            for td in soup.find_all("td", attrs={"colspan": "3"}):
                text = td.get_text()
                m = re.search(r"([A-Z]{2})\s*-?\s*(\d{5})", text)
                if m:
                    job_id = f"{m.group(1)}-{m.group(2)}"
                    break

    missing = [
        k
        for k, v in {
            "customer_name": customer_name,
            "claim_number": claim_number,
            "job_location": job_location,
        }.items()
        if not v
    ]
    if missing:
        raise RuntimeError(
            f"Could not find fields: {', '.join(missing)}. "
            "The page structure may have changed."
        )

    return {
        "customer_name": customer_name,
        "claim_number": claim_number,
        "job_location": job_location,
        "job_id": job_id,
        "sales_rep": sales_rep,
    }
