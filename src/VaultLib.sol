// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {
    IFWAV2, IFWAToken, IFloorOracle, IPoolManager, PoolKey, SwapParams
} from "./interfaces/External.sol";

/// @notice Linked library for PackVault: the live FWA economics read and the token pool swap.
///         Split out only to keep PackVault under EIP-170; both run in the vault's context
///         (delegatecall) and hold no state of their own.
library VaultLib {
    using SafeTransferLib for address;

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

    /// @notice v4 exact-input sell of FWA (currency1) for native ETH (currency0), run inside the
    ///         pool manager's unlock callback. Pays the tokens in and takes the ETH out.
    function swapTokens(IPoolManager pm, IFWAToken token, uint256 amount) external {
        PoolKey memory key = token.poolKey();
        int256 delta = pm.swap(
            key,
            SwapParams({
                zeroForOne: false,
                amountSpecified: -int256(amount),
                sqrtPriceLimitX96: 1_461_446_703_485_210_103_287_273_052_203_988_822_378_723_970_341
            }),
            ""
        );
        uint256 tokensIn = uint256(uint128(-int128(delta)));
        uint256 ethOut = uint256(uint128(int128(delta >> 128)));
        pm.sync(key.currency1);
        address(token).safeTransfer(address(pm), tokensIn);
        pm.settle();
        pm.take(address(0), address(this), ethOut);
    }
}
