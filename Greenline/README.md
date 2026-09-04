# Canopy Ledger — parcel-based carbon credit MRV prototype

An end-to-end technical prototype: a parcel owner draws their land boundary in a
browser, a backend runs Google Earth Engine NDVI analysis and land-cover
classification over that boundary, a carbon credit amount is calculated, and
credits are minted to the owner's wallet by a smart contract on a Layer 2 chain.

## Architecture

```
frontend/index.html        Map UI: draw parcel boundary, enter owner details,
                            connect wallet, submit for verification.
                                |
                                v
backend/api.py              FastAPI service: stores submissions, triggers
                            verification, calls the smart contract.
                                |
                    +-----------+-----------+
                    v                       v
backend/gee_processor.py       backend/carbon_credit_calculator.py
Sentinel-2 composite,          NDVI -> biomass proxy -> tCO2e,
NDVI, land-cover mask           buffer pool deduction.
                    |                       |
                    +-----------+-----------+
                                v
contracts/CarbonCredit.sol   ERC20 credit token. VERIFIER_ROLE (the backend's
                            oracle wallet) mints credits after verification;
                            holders can retire (burn) credits to claim an offset.
```

## Running it

**Frontend** — `frontend/index.html` runs standalone in a browser (it uses
Leaflet + Leaflet.draw + ethers.js from a CDN). Set `API_BASE_URL` near the top
of the `<script>` block to your deployed `backend/api.py` URL. Until you do,
the boundary-drawing and estimate preview still work locally; only the final
submit call needs the backend.

**Backend**
```bash
cd backend
pip install -r requirements.txt
export GEE_SERVICE_ACCOUNT="your-sa@your-project.iam.gserviceaccount.com"
export GEE_KEY_FILE="/path/to/service-account-key.json"
export CONTRACT_ADDRESS="0x..."
export CONTRACT_ABI_PATH="../contracts/artifacts/contracts/CarbonCredit.sol/CarbonCredit.json"
export RPC_URL="https://rpc-amoy.polygon.technology"
export VERIFIER_PRIVATE_KEY="0x..."   # the oracle wallet granted VERIFIER_ROLE
uvicorn api:app --reload
```
You'll need a Google Earth Engine account with Earth Engine API access enabled
on a Google Cloud project, and a service account with Earth Engine permissions
(https://developers.google.com/earth-engine/guides/service_account).

**Contracts**
```bash
cd contracts
npm install
npx hardhat compile
npx hardhat run deploy.js --network polygonAmoy
```
After deploying, grant the backend's oracle wallet `VERIFIER_ROLE` (the deploy
script prints the exact call). Point `CONTRACT_ADDRESS` and `CONTRACT_ABI_PATH`
in the backend at the deployed contract and its compiled ABI.

## What's simplified, and what you'd need for real credit issuance

This prototype is built to be genuinely runnable end-to-end, but two parts are
placeholders you should treat as such:

- **Land-cover classification** (`gee_processor.classify_land_cover`) uses
  unsupervised k-means clustering as a stand-in for a properly trained,
  ground-truthed classifier. Production use needs labeled reference plots for
  your region and ecosystem.
- **NDVI-to-carbon conversion** (`carbon_credit_calculator.ndvi_to_biomass_density`)
  is a simple linear proxy, not a calibrated allometric biomass model. Actual
  carbon credit issuance that can be sold on voluntary or compliance markets
  requires a registered methodology (e.g. Verra VM0042, Gold Standard, CDM
  AR-ACM0003), field calibration, additionality/baseline/leakage assessment,
  and independent third-party verification before any credits are considered
  real. This pipeline automates the technical MRV steps a methodology would
  sit on top of — it isn't itself an accredited registry.

## Security notes before any mainnet deployment

- `VERIFIER_ROLE` is a single point of trust — anyone holding that key can
  mint credits. Consider a multisig or a decentralized oracle network (e.g.
  Chainlink Functions calling out to the Earth Engine pipeline) instead of one
  backend-held private key.
- Get the contract audited before handling real funds or credits with market
  value.
- The `evidenceHash` on each issuance should point to a permanently stored,
  publicly retrievable verification report (e.g. pinned to IPFS) so issuances
  are independently auditable.
