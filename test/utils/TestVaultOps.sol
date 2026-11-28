// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm, VmSafe} from "forge-std/Vm.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {IFloorOracle} from "../../src/interfaces/External.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @dev Test references may enumerate bounded getters; production keepers use indexed events.
library TestVaultOps {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private constant QUANTUM = 10_000;

    /// @dev Fund through the real receive path; never fabricate an account's balance.
    function fundTo(PackAccount account, uint256 balance) internal {
        require(balance >= address(account).balance, "funding cannot remove account cash");
        (bool ok,) = address(account).call{value: balance - address(account).balance}("");
        require(ok, "account funding failed");
    }

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
        uint256 minimum = 1;
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

    // Packed into one memory pointer so inlined ops spend one stack slot here, not three (via_ir depth).
    struct Prank { VmSafe.CallerMode mode; address sender; address origin; }

    function _pausePrank() private returns (Prank memory p) {
        (p.mode, p.sender, p.origin) = vm.readCallers();
        if (p.mode == VmSafe.CallerMode.Prank) vm.stopPrank();
    }

    function _resumePrank(Prank memory p) private {
        if (p.mode == VmSafe.CallerMode.Prank) vm.prank(p.sender, p.origin);
    }

    function configurationHash(PackAccount account) internal returns (bytes32 expected) {
        Prank memory p = _pausePrank();
        expected = account.configurationHash();
        _resumePrank(p);
    }

    function factoryHash(PackManagerFactory factory, VaultLib.Params memory params) internal returns (bytes32 expected) {
        Prank memory p = _pausePrank();
        expected = factory.configHashFor(params);
        _resumePrank(p);
    }

    /// @dev Build-and-list `n` new packs of `units`, in batches of MAX_BUILD_BATCH.
    function restock(PackAccount v, uint256 n, uint256 units, uint256 minPay) internal returns (uint256 pay) {
        Prank memory _pk = _pausePrank();
        while (n != 0) {
            uint256 batch = n < v.MAX_BUILD_BATCH() ? n : v.MAX_BUILD_BATCH();
            uint256[] memory quotes = proposals(v, batch, units);
            _resumePrank(_pk);
            bytes32 _expected0 = configurationHash(v);
            pay += v.build(units, quotes, minPay, _expected0);
            n -= batch;
        }
    }

    function list(PackAccount v, uint256 n, uint256 minPay) internal returns (uint256 pay) {
        Prank memory _pk = _pausePrank();
        uint256 available = v.idlePackCount();
        if (n > available) n = available;
        // `restock` builds and lists at once; a following list of nothing is a no-op.
        if (n == 0) {
            _resumePrank(_pk);
            return 0;
        }
        while (n != 0) {
            uint256 batch = 1;
            uint256 pack = v.idlePackAt(v.idlePackCount() - 1);
            (, uint256 target,) = v.relistEdgeFor(pack);
            uint256[] memory quotes = new uint256[](1);
            uint256 radius = v.reservedCount() + 1;
            uint256 base = (target + QUANTUM - 1) / QUANTUM * QUANTUM;
            bool found;
            for (uint256 d; d <= radius && !found; ++d) {
                for (uint256 side; side < 2; ++side) {
                    if (side == 0 && base < d * QUANTUM) continue;
                    uint256 candidate = side == 0 ? base - d * QUANTUM : base + (d + 1) * QUANTUM;
                    if (candidate != 0 && v.idForBacking(candidate) == 0) {
                        quotes[0] = candidate; found = true; break;
                    }
                }
            }
            require(found, "test relist interval exhausted");
            _resumePrank(_pk);
            bytes32 _expected1 = configurationHash(v);
            pay += v.list(quotes, minPay, _expected1);
            n -= batch;
        }
    }

    function sync(PackAccount v, uint256[] memory ids, uint256 minPay) internal returns (uint256 pay) {
        Prank memory _pk = _pausePrank();
        bytes32 _expected2 = configurationHash(v);
        if (ids.length <= 16) { _resumePrank(_pk); return v.sync(ids, 0, minPay, _expected2); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 count = ids.length - start < 16 ? ids.length - start : 16;
            uint256[] memory batch = new uint256[](count);
            for (uint256 i; i < count; ++i) batch[i] = ids[start + i];
            _resumePrank(_pk);
            bytes32 _expected3 = configurationHash(v);
            pay += v.sync(batch, 0, minPay, _expected3);
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
        Prank memory _pk = _pausePrank();
        bytes32 _expected4 = configurationHash(v);
        if (ids.length == 0) { _resumePrank(_pk); return v.unlist(ids, minPay, _expected4); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(_pk);
            bytes32 _expected5 = configurationHash(v);
            pay += v.unlist(_slice(ids, start, n), minPay, _expected5);
        }
    }

    function harvest(PackAccount v, uint256[] memory ids, uint256 minPay) internal returns (uint256 pay) {
        Prank memory _pk = _pausePrank();
        _sort(ids);
        if (ids.length == 0) { _resumePrank(_pk); return v.harvest(ids, minPay); }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(_pk);
            pay += v.harvest(_slice(ids, start, n), minPay);
        }
    }

    function burnTokens(PackAccount v, uint256[] memory ids) internal {
        Prank memory _pk = _pausePrank();
        _sort(ids);
        if (ids.length == 0) { _resumePrank(_pk); v.burnTokens(ids); return; }
        for (uint256 start; start < ids.length; start += 16) {
            uint256 n = ids.length - start < 16 ? ids.length - start : 16;
            _resumePrank(_pk);
            v.burnTokens(_slice(ids, start, n));
        }
    }

    function checkpoint(PackVault v, uint256 minPay) internal returns (uint256) {
        Prank memory _pk = _pausePrank();
        uint256 id = witness(v);
        _resumePrank(_pk);
        bytes32 _expected6 = configurationHash(v);
        return v.checkpoint(id, minPay, _expected6);
    }
}
