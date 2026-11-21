// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm, VmSafe} from "forge-std/Vm.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {IFloorOracle} from "../../src/interfaces/External.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @dev Test references may enumerate bounded getters; production keepers use indexed events.
library TestVaultOps {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private constant QUANTUM = 10_000;

    function open(PackAccount v) internal view returns (uint256[] memory ids) {
        ids = new uint256[](v.openListingCount());
        for (uint256 i; i < ids.length; ++i) ids[i] = v.openListingAt(i);
    }

    function idle(PackAccount v) internal view returns (uint256[] memory ids) {
        ids = new uint256[](v.idlePackCount());
        for (uint256 i; i < ids.length; ++i) ids[i] = v.idlePackAt(i);
    }

    function position(PackAccount v, uint256 id) internal view returns (uint64 pack, uint64 units, uint128 backing) {
        VaultLib.Position memory p = v.position(id);
        return (uint64(p.packId), uint64(p.value / 0.01 ether), uint128(p.backing));
    }

    function witness(PackAccount v) internal view returns (uint256 id) {
        uint256 debt = type(uint256).max;
        uint256[] memory ids = open(v);
        for (uint256 i; i < ids.length; ++i) {
            (,,,,,,, uint256 d,,, uint8 status) = v.fwa().listings(ids[i]);
            if (status == 1 && d < debt) { id = ids[i]; debt = d; }
        }
    }

    /// @dev An offchain search. The onchain admission path independently validates each proposal.
    function proposals(PackAccount v, uint256 n, uint256 units) internal view returns (uint256[] memory quotes) {
        quotes = new uint256[](n);
        (, uint256 target,) = v.edge(units);
        if (target == 0) return quotes;
        // A keep never loses at FWA's 5% settlement-fee cap: at least P / 0.95.
        uint256 minimum = (units * 0.01 ether * 10_000 + 9_499) / 9_500;
        uint256 radius = v.reservedCount() + n + 1;
        uint256 base = (target + QUANTUM - 1) / QUANTUM * QUANTUM;
        bool exempt = v.fwa().oracleExemptCollections(address(v.packs()));
        uint256 ceiling = type(uint256).max;
        if (!exempt) {
            (, uint256 ask,,) = IFloorOracle(v.fwa().floorOracle()).getFloorRange(address(v.packs()));
            ceiling = ask * (10_000 + v.fwa().oracleCeilingPremiumBps()) / 10_000;
            ceiling = ceiling * (10_000 - v.getParams().bufferBps) / 10_000;
        }
        for (uint256 i; i < n; ++i) {
            bool found;
            for (uint256 distance; distance <= radius && !found; ++distance) {
                for (uint256 side; side < 2; ++side) {
                    if (side == 0 && base < distance * QUANTUM) continue;
                    uint256 b = side == 0 ? base - distance * QUANTUM : base + (distance + 1) * QUANTUM;
                    if (b < minimum || v.idForBacking(b) != 0 || b > ceiling) continue;
                    bool used;
                    for (uint256 j; j < i; ++j) if (quotes[j] == b) used = true;
                    if (!used) { quotes[i] = b; found = true; break; }
                }
            }
            require(found, "test quote interval exhausted");
        }
    }

    function _pausePrank() private returns (VmSafe.CallerMode mode, address sender, address origin) {
        (mode, sender, origin) = vm.readCallers();
        if (mode == VmSafe.CallerMode.Prank) vm.stopPrank();
    }

    function _resumePrank(VmSafe.CallerMode mode, address sender, address origin) private {
        if (mode == VmSafe.CallerMode.Prank) vm.prank(sender, origin);
    }

    /// @dev Build-and-list `n` new packs of `units`, in batches of MAX_LIST_BATCH.
    function restock(PackAccount v, uint256 n, uint256 units, uint256 minPay) internal returns (uint256 pay) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        while (n != 0) {
            uint256 batch = n < v.MAX_LIST_BATCH() ? n : v.MAX_LIST_BATCH();
            uint256[] memory quotes = proposals(v, batch, units);
            _resumePrank(mode, sender, origin);
            pay += v.build(units, quotes, minPay);
            n -= batch;
        }
    }

    function list(PackAccount v, uint256 n, uint256 minPay) internal returns (uint256 pay) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        uint256 available = v.idlePackCount();
        if (n > available) n = available;
        // `restock` builds and lists at once; a following list of nothing is a no-op.
        if (n == 0) {
            _resumePrank(mode, sender, origin);
            return 0;
        }
        while (n != 0) {
            uint256 limit = v.MAX_LIST_BATCH();
            uint256 batch = n < limit ? n : limit;
            uint256 pack = v.idlePackAt(v.idlePackCount() - 1);
            uint256 units = v.packs().valueOf(pack) / 0.01 ether;
            uint256[] memory quotes = proposals(v, batch, units);
            _resumePrank(mode, sender, origin);
            pay += v.list(quotes, minPay);
            n -= batch;
        }
    }

    function sync(PackAccount v, uint256[] memory ids, uint256 minPay) internal returns (uint256 pay) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        if (ids.length <= 16) { _resumePrank(mode, sender, origin); return v.sync(ids, 0, minPay); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 count = ids.length - start < 16 ? ids.length - start : 16;
            uint256[] memory batch = new uint256[](count);
            for (uint256 i; i < count; ++i) batch[i] = ids[start + i];
            _resumePrank(mode, sender, origin);
            pay += v.sync(batch, 0, minPay);
        }
    }

    function _slice(uint256[] memory ids, uint256 start, uint256 n) private pure returns (uint256[] memory batch) {
        batch = new uint256[](n);
        for (uint256 i; i < n; ++i) batch[i] = ids[start + i];
    }

    function _sort(uint256[] memory ids) private pure {
        for (uint256 i = 1; i < ids.length; ++i) {
            uint256 value = ids[i]; uint256 j = i;
            while (j != 0 && ids[j - 1] > value) { ids[j] = ids[j - 1]; --j; }
            ids[j] = value;
        }
    }

    function unlist(PackAccount v, uint256[] memory ids, uint256 minPay) internal returns (uint256 pay) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        if (ids.length == 0) { _resumePrank(mode, sender, origin); return v.unlist(ids, minPay); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(mode, sender, origin);
            pay += v.unlist(_slice(ids, start, n), minPay);
        }
    }

    function harvest(PackAccount v, uint256[] memory ids, uint256 minPay) internal returns (uint256 pay) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        _sort(ids);
        if (ids.length == 0) { _resumePrank(mode, sender, origin); return v.harvest(ids, minPay); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(mode, sender, origin);
            pay += v.harvest(_slice(ids, start, n), minPay);
        }
    }

    function burnTokens(PackAccount v, uint256[] memory ids) internal {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        _sort(ids);
        if (ids.length == 0) { _resumePrank(mode, sender, origin); v.burnTokens(ids); return; }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(mode, sender, origin);
            v.burnTokens(_slice(ids, start, n));
        }
    }

    function checkpoint(PackVault v, uint256 minPay) internal returns (uint256) {
        (VmSafe.CallerMode mode, address sender, address origin) = _pausePrank();
        uint256 id = witness(v);
        _resumePrank(mode, sender, origin);
        return v.checkpoint(id, minPay);
    }
}
