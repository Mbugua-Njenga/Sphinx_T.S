"""
api.py

FastAPI backend for the Canopy Ledger MRV pipeline.

Endpoints:
  POST /api/parcels/submit   - Owner submits parcel boundary + details (called by frontend/index.html)
  GET  /api/parcels/{id}     - Check verification/issuance status
  POST /api/parcels/{id}/verify - Trigger NDVI/classification + on-chain issuance (internal/admin)

Run:
    pip install fastapi uvicorn web3 python-dotenv
    uvicorn api:app --reload

Requires:
  - Earth Engine service account credentials (see gee_processor.init_earth_engine)
  - An RPC endpoint and a funded VERIFIER_ROLE wallet for the deployed CarbonCredit contract
"""

import os
import json
import uuid
import hashlib
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from web3 import Web3

import gee_processor
from carbon_credit_calculator import calculate_credits

app = FastAPI(title="Canopy Ledger MRV API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict to your frontend's origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- naive in-memory store for a prototype; use a real database in production ----
PARCELS: dict[str, dict] = {}

CONTRACT_ABI_PATH = os.environ.get("CONTRACT_ABI_PATH", "CarbonCredit.abi.json")
CONTRACT_ADDRESS = os.environ.get("CONTRACT_ADDRESS", "")
RPC_URL = os.environ.get("RPC_URL", "https://rpc-amoy.polygon.technology")
VERIFIER_PRIVATE_KEY = os.environ.get("VERIFIER_PRIVATE_KEY", "")


class OwnerDetails(BaseModel):
    name: str
    email: str | None = None
    country: str | None = None
    wallet_address: str | None = None


class ParcelBoundary(BaseModel):
    name: str
    title_id: str | None = None
    boundary: dict  # GeoJSON Polygon


class ParcelSubmission(BaseModel):
    owner: OwnerDetails
    parcel: ParcelBoundary


class VerifyRequest(BaseModel):
    start_date: str = Field(default_factory=lambda: (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d"))
    end_date: str = Field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d"))


def get_web3_contract():
    if not CONTRACT_ADDRESS:
        raise HTTPException(500, "CONTRACT_ADDRESS is not configured on the backend")
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    with open(CONTRACT_ABI_PATH) as f:
        abi = json.load(f)
    contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=abi)
    return w3, contract


@app.post("/api/parcels/submit")
def submit_parcel(submission: ParcelSubmission):
    if submission.owner.wallet_address and not Web3.is_address(submission.owner.wallet_address):
        raise HTTPException(400, "wallet_address is not a valid address")

    parcel_id = str(uuid.uuid4())
    PARCELS[parcel_id] = {
        "id": parcel_id,
        "owner": submission.owner.model_dump(),
        "parcel": submission.parcel.model_dump(),
        "status": "submitted",
        "submitted_at": datetime.utcnow().isoformat(),
        "stats": None,
        "estimate": None,
        "issuance_tx": None,
    }
    return {"parcel_id": parcel_id, "status": "submitted"}


@app.get("/api/parcels/{parcel_id}")
def get_parcel(parcel_id: str):
    record = PARCELS.get(parcel_id)
    if not record:
        raise HTTPException(404, "parcel not found")
    return record


@app.post("/api/parcels/{parcel_id}/verify")
def verify_and_issue(parcel_id: str, req: VerifyRequest):
    """Runs the real Earth Engine NDVI/classification pipeline, calculates the
    creditable tonnage, and mints credits on-chain to the owner's wallet.

    This endpoint should be restricted to an internal scheduler or admin caller,
    not exposed directly to parcel owners, since it commits gas-spending
    transactions and represents the actual verification decision.
    """
    record = PARCELS.get(parcel_id)
    if not record:
        raise HTTPException(404, "parcel not found")
    if not record["owner"].get("wallet_address"):
        raise HTTPException(400, "parcel has no payout wallet on file")

    gee_processor.init_earth_engine()
    stats = gee_processor.compute_parcel_stats(
        record["parcel"]["boundary"], req.start_date, req.end_date
    )
    estimate = calculate_credits(stats)

    evidence_payload = json.dumps({"parcel_id": parcel_id, "stats": stats}, sort_keys=True)
    evidence_hash = "0x" + hashlib.sha256(evidence_payload.encode()).hexdigest()

    amount_wei = int(estimate.creditable_tons * (10**18))
    area_scaled = int(estimate.vegetated_area_ha * 1e4)
    ndvi_scaled = int((estimate.mean_ndvi_vegetated or 0) * 1e4)

    w3, contract = get_web3_contract()
    verifier_account = w3.eth.account.from_key(VERIFIER_PRIVATE_KEY)

    tx = contract.functions.issueCredits(
        record["parcel"]["name"],
        Web3.to_checksum_address(record["owner"]["wallet_address"]),
        amount_wei,
        area_scaled,
        ndvi_scaled,
        Web3.to_bytes(hexstr=evidence_hash),
    ).build_transaction({
        "from": verifier_account.address,
        "nonce": w3.eth.get_transaction_count(verifier_account.address),
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=VERIFIER_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    record["status"] = "issued"
    record["stats"] = stats
    record["estimate"] = estimate.__dict__
    record["issuance_tx"] = tx_hash.hex()

    return {
        "parcel_id": parcel_id,
        "status": "issued",
        "stats": stats,
        "estimate": estimate.__dict__,
        "tx_hash": tx_hash.hex(),
    }
