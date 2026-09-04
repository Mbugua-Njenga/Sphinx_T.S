// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

/// @title CarbonCredit
/// @notice ERC20 token representing verified carbon credits (1 token = 1 tCO2e),
/// minted only by an authorized VERIFIER_ROLE after off-chain NDVI/classification
/// verification, and retired (burned) when a buyer claims an offset.
/// @dev Intended for deployment on a low-fee Layer 2 (e.g. Polygon PoS/zkEVM,
/// Optimism, Arbitrum, Base) so per-parcel issuance transactions stay cheap.
/// This contract handles issuance and retirement bookkeeping only. It does not
/// itself constitute a registered carbon registry — see README for the
/// distinction between this and an accredited MRV/registry system.
contract CarbonCredit is ERC20, AccessControl, Pausable {
    bytes32 public constant VERIFIER_ROLE = keccak256("VERIFIER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");

    struct ParcelIssuance {
        string parcelId;       // off-chain parcel identifier, matches backend records
        address owner;         // payout wallet of the parcel owner
        uint256 amount;        // credits issued (18 decimals, like the token)
        uint256 areaHaScaled;  // hectares * 1e4, avoids floating point on-chain
        uint256 ndviScaled;    // mean vegetated NDVI * 1e4
        uint256 timestamp;
        bytes32 evidenceHash;  // hash of the off-chain verification report (IPFS CID or similar)
    }

    mapping(uint256 => ParcelIssuance) public issuances;
    uint256 public issuanceCount;

    // Prevents the same off-chain verification report from being submitted twice.
    mapping(bytes32 => bool) public evidenceHashUsed;

    event CreditsIssued(
        uint256 indexed issuanceId,
        string parcelId,
        address indexed owner,
        uint256 amount,
        bytes32 evidenceHash
    );
    event CreditsRetired(address indexed holder, uint256 amount, string reason);

    constructor(address admin) ERC20("Canopy Ledger Carbon Credit", "CLCC") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(VERIFIER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
    }

    /// @notice Mint credits to a parcel owner after off-chain verification.
    /// @param parcelId Off-chain parcel identifier.
    /// @param owner Payout wallet address of the parcel owner.
    /// @param amount Credit amount to mint, in whole tokens with 18 decimals applied by the caller.
    /// @param areaHaScaled Vegetated area in hectares, scaled by 1e4.
    /// @param ndviScaled Mean vegetated NDVI, scaled by 1e4.
    /// @param evidenceHash Hash (e.g. keccak256 of an IPFS CID) of the verification report,
    /// so the on-chain record is auditable against the off-chain NDVI/classification output.
    function issueCredits(
        string calldata parcelId,
        address owner,
        uint256 amount,
        uint256 areaHaScaled,
        uint256 ndviScaled,
        bytes32 evidenceHash
    ) external onlyRole(VERIFIER_ROLE) whenNotPaused returns (uint256 issuanceId) {
        require(owner != address(0), "owner is zero address");
        require(amount > 0, "amount must be positive");
        require(!evidenceHashUsed[evidenceHash], "evidence already used");

        evidenceHashUsed[evidenceHash] = true;
        issuanceId = issuanceCount++;

        issuances[issuanceId] = ParcelIssuance({
            parcelId: parcelId,
            owner: owner,
            amount: amount,
            areaHaScaled: areaHaScaled,
            ndviScaled: ndviScaled,
            timestamp: block.timestamp,
            evidenceHash: evidenceHash
        });

        _mint(owner, amount);
        emit CreditsIssued(issuanceId, parcelId, owner, amount, evidenceHash);
    }

    /// @notice Permanently retire (burn) credits from the caller's own balance,
    /// e.g. when a buyer claims an offset. Retired credits cannot be resold.
    function retire(uint256 amount, string calldata reason) external whenNotPaused {
        _burn(msg.sender, amount);
        emit CreditsRetired(msg.sender, amount, reason);
    }

    function pause() external onlyRole(PAUSER_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
    }

    function _update(address from, address to, uint256 value)
        internal
        override
        whenNotPaused
    {
        super._update(from, to, value);
    }
}
