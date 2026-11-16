// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {ERC721} from "solady/tokens/ERC721.sol";

/// @dev Sends ETH by self-destruct: arrives with no call, as FWA's forceSafeTransferETH can.
contract ForceSender {
    constructor(address payable to) payable {
        selfdestruct(to);
    }
}

/// @dev An attacker-chosen NFT collection pushing tokens at the vault.
contract HostileNft is ERC721 {
    function name() public pure override returns (string memory) {
        return "Hostile";
    }

    function symbol() public pure override returns (string memory) {
        return "H";
    }

    function tokenURI(uint256) public pure override returns (string memory) {
        return "";
    }

    function mint(address to, uint256 id) external {
        _mint(to, id);
    }
}

/// @dev Holder that tries to re-enter the vault from its ETH receive hook.
contract ReentrantHolder {
    PackVault immutable vault;
    uint256 public reentryReverted;

    constructor(PackVault v) {
        vault = v;
    }

    function deposit() external payable {
        vault.deposit{value: msg.value}();
    }

    function redeemAll() external {
        vault.requestRedeem(vault.shareBalance(address(this)));
    }

    function claim() external {
        vault.claim();
    }

    receive() external payable {
        try vault.claim() {} catch {
            ++reentryReverted;
        }
    }
}

contract ForkVaultAdversarialTest is ForkBase {
    function test_gasPriceAboveCeilingBlocksSpending() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.txGasPrice(6 gwei); // ceiling is 5 gwei
        vm.prank(keeper);
        vm.expectRevert(PackVault.GasPrice.selector);
        vault.restock(1, 3);
        vm.txGasPrice(0.2 gwei);
        vm.prank(keeper);
        vault.restock(1, 3);
    }

    function test_forcedEthAccruesToHolders_firstDepositorCannotInflate() public {
        // Attacker is first depositor with the minimum, then donates 10 ETH before the victim prices.
        address attacker = makeAddr("pack-vault-test-attacker");
        vm.deal(attacker, 20 ether);
        vm.prank(attacker);
        vault.deposit{value: 0.01 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(attacker);
        new ForceSender{value: 10 ether}(payable(address(vault)));
        vm.prank(alice);
        vault.deposit{value: 5 ether}();
        toBlackout();
        checkpoint();

        uint256 supply = vault.totalShares();
        uint256 aliceShares = vault.shareBalance(alice);
        uint256 nav = vault.lastNav();
        // Alice's claim on NAV equals what she paid in, to the wei-scale rounding of share math.
        assertApproxEqAbs(nav * aliceShares / supply, 5 ether, 1e10, "victim keeps her deposit");
        // The donation is shared by everyone who held shares before it, dead shares included.
        uint256 seed = 0.01 ether + preexisting;
        uint256 attackerValue = nav * vault.shareBalance(attacker) / supply;
        assertApproxEqAbs(attackerValue, (0.01 ether + 10 ether) - 10 ether * seed / (seed + 0.01 ether), 1e10);
        assertLt(attackerValue, 10.01 ether, "attacker loses part of the donation to the seed");
    }

    function test_hostileNftRejected() public {
        HostileNft h = new HostileNft();
        h.mint(address(this), 1);
        vm.expectRevert(PackVault.UnknownNft.selector);
        h.safeTransferFrom(address(this), address(vault), 1);
    }

    function test_reentrantHolderClaimsOnce() public {
        ReentrantHolder r = new ReentrantHolder(vault);
        vm.deal(address(r), 0);
        r.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        r.redeemAll();
        toBlackout();
        checkpoint();
        uint256 owed = vault.claimableEth(address(r));
        r.claim();
        // Holder-side rounding is down: at most 1 wei short, never over.
        assertApproxEqAbs(address(r).balance, 1 ether, 1, "claimed its redemption");
        assertLe(address(r).balance, 1 ether);
        assertEq(owed, 0, "claimable is settled lazily inside claim");
        assertEq(r.reentryReverted(), 1, "re-entry from receive reverted");
        vm.expectRevert(PackVault.Nothing.selector);
        r.claim();
    }

    function test_distributionPaysGainsOnce() public {
        PackVault.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        assertGe(address(vault).balance, 0.01 ether); // deploy addresses can hold mainnet dust
        vm.prank(alice);
        vault.deposit{value: 4 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        new ForceSender{value: 1 ether}(payable(address(vault)));
        toBlackout();
        checkpoint();
        uint256 distributed = vault.distributionReserve();
        // 20% of the 1 ETH gain, gain measured above the high-water mark.
        assertApproxEqAbs(distributed, 0.2 ether, 1e6);
        uint256 supply = vault.totalShares();
        uint256 aliceShare = 0.2 ether * vault.shareBalance(alice) / supply;
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertApproxEqAbs(alice.balance - before, aliceShare, 1e6);
        // Next checkpoint with no new gain pays nothing more.
        toOpen();
        toBlackout();
        checkpoint();
        assertApproxEqAbs(vault.distributionReserve(), distributed - (alice.balance - before), 1);
        // The dead shares' slice of the distribution stays reserved forever (accepted, D13).
        assertApproxEqAbs(vault.distributionReserve(), 0.2 ether * vault.DEAD_SHARES() / supply, 1e6);
    }

    function test_depositAboveTvlCapReverts() public {
        vm.prank(guardian);
        vault.lowerCaps(1 ether, 150, 5 gwei);
        vm.prank(alice);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 1.5 ether}();
    }

    function test_checkpointWindowRules() public {
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint();
        toBlackout();
        vault.checkpoint();
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint();
    }
}
