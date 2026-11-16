// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {IFWAV2, IFloorOracle} from "./interfaces/External.sol";

/// @notice Linked library for PackVault: the live FWA economics read. Split out only to keep
///         PackVault under EIP-170; it runs in the vault's context and holds no state.
library VaultLib {
    uint256 internal constant BPS = 10_000;

    /// @notice Live k (1e18 scale) and FWA's backing cap for `packs` (zero when FWA would refuse
    ///         a listing). k = (1 + surcharge)(1 - protocolCut)(1 - crownShare).
    function economics(IFWAV2 f, address packs) external view returns (uint256 k1e18, uint256 cap, uint256 s) {
        s = f.ownerSettlementFeeBps();
        uint256 w = f.totalWeight();
        if (w == 0) return (0, 0, s);
        // FWA exposes no getter for its surcharge: acquisitionFee = (wbt / w) (1 + surcharge).
        uint256 ev = f.weightedBackingTotal() / w;
        uint256 oneSur = f.acquisitionFee() * 1e18 / ev; // 1e18 x (1 + surcharge), floors
        k1e18 = oneSur * (BPS - f.ownerAcquisitionFeeBps()) / BPS * (BPS - f.topListingShareBps()) / BPS;
        if (!f.canDeposit(packs) || f.oracleExemptCollections(packs)) return (k1e18, 0, s);
        // The oracle ask plus premium when the quote passes FWA's own validity rules.
        // A failing or malformed oracle means no cap (nothing new lists); it must not block
        // unlisting, wind-down or redemptions. FWA's owner can repoint the oracle to any contract,
        // so the read is a raw staticcall: a revert or short return data both mean "no cap".
        (bool ok, bytes memory ret) =
            f.floorOracle().staticcall(abi.encodeCall(IFloorOracle.getFloorRange, (packs)));
        if (!ok || ret.length < 128) return (k1e18, 0, s);
        (uint256 bid, uint256 ask, uint48 observedAt, uint48 periodUsed) =
            abi.decode(ret, (uint256, uint256, uint48, uint48));
        if (bid == 0 || bid >= ask || observedAt == 0 || observedAt > block.timestamp) return (k1e18, 0, s);
        if (block.timestamp - observedAt > f.maxOracleAge()) return (k1e18, 0, s);
        if (periodUsed < f.minOracleChallengePeriod()) return (k1e18, 0, s);
        cap = ask * (BPS + f.oracleCeilingPremiumBps()) / BPS;
    }
}
