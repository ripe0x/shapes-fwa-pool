// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {IShapes, IShapePacks} from "../../src/interfaces/External.sol";

interface IShapePacksMint {
    function createPack(uint256[] calldata shapeIds, uint32[] calldata mintCounts) external payable returns (uint256);
    function redeem(uint256 packId) external;
    function valueOf(uint256 packId) external view returns (uint256);
    function contentsOf(uint256 packId) external view returns (uint256[] memory);
}

/// @notice Measures ShapePacks' native direct-mint construction on the real contracts: Shapes are
///         minted straight into the pack with one paid primary mint fee each, no split.
contract ForkDirectMintTest is Test {
    uint256 constant BLOCK = 26_424_971;
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacksMint constant PACKS = IShapePacksMint(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    address buyer = makeAddr("pack-vault-test-direct-mint");

    function setUp() public {
        vm.createSelectFork("mainnet", BLOCK);
        assertEq(buyer.code.length, 0);
        assertEq(buyer.balance, 0);
        vm.deal(buyer, 10 ether);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    receive() external payable {}

    function _make(uint32 c001, uint32 c005, uint32 c01) internal returns (uint256 packId, uint256 gasUsed) {
        uint32[] memory counts = new uint32[](9);
        (counts[0], counts[1], counts[2]) = (c001, c005, c01);
        uint256 shapesN = uint256(c001) + c005 + c01;
        uint256 value = c001 * 0.01 ether + c005 * 0.05 ether + c01 * 0.1 ether;
        uint256 fee = SHAPES.mintFee();
        vm.deal(address(this), 10 ether);
        uint256 balBefore = address(this).balance;
        uint256 supplyBefore = SHAPES.totalSupply();
        uint256 g = gasleft();
        packId = PACKS.createPack{value: value + shapesN * fee}(new uint256[](0), counts);
        gasUsed = g - gasleft();
        assertEq(PACKS.valueOf(packId), value, "pack value");
        assertEq(PACKS.contentsOf(packId).length, shapesN, "one minted Shape per count");
        assertEq(SHAPES.totalSupply() - supplyBefore, shapesN, "paid primary mints");
        assertEq(balBefore - address(this).balance, value + shapesN * fee, "exact payment: value + fee per Shape");
    }

    function test_directMintRecipes() public {
        (uint256 p6, uint256 g6) = _make(1, 1, 0); // 0.06 = 0.05 + 0.01: two mint fees
        (, uint256 g3) = _make(3, 0, 0); // 0.03 = 3 x 0.01: three mint fees
        (, uint256 g7) = _make(2, 1, 0); // 0.07 = 0.05 + 2 x 0.01: three mint fees
        (, uint256 g5) = _make(0, 1, 0); // 0.05 alone: one mint fee
        emit log_named_uint("gas createPack 0.06 (2 Shapes)", g6);
        emit log_named_uint("gas createPack 0.03 (3 Shapes)", g3);
        emit log_named_uint("gas createPack 0.07 (3 Shapes)", g7);
        emit log_named_uint("gas createPack 0.05 (1 Shape)", g5);
        uint256 before = address(this).balance;
        uint256 g = gasleft();
        PACKS.redeem(p6);
        emit log_named_uint("gas redeem 0.06 pack (2 Shapes)", g - gasleft());
        assertEq(address(this).balance - before, 0.06 ether, "redeem returns exact backing, no fee");
    }
}
