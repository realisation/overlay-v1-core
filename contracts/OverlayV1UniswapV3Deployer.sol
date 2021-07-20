// SPDX-License-Identifier: MIT
pragma solidity ^0.8.2;

import "./OverlayV1UniswapV3Market.sol";

contract OverlayV1UniswapV3Deployer {

    /// @notice Creates a new market contract for given mirin pool address
    function deployMarket(
        address ovl,
        address uniPool,
        uint256 updatePeriod,
        uint144 oiCap,
        uint112 fundingKNumerator,
        uint112 fundingKDenominator,
        uint16  marginAdjustment,
        uint8   leverageMax,
        uint256 windowSize,
        uint128 amountIn,
        bool    isPrice0
    ) external returns (OverlayV1UniswapV3Market marketContract) {
        marketContract = new OverlayV1UniswapV3Market(
            ovl,
            uniPool,
            updatePeriod,
            oiCap,
            fundingKNumerator,
            fundingKDenominator,
            marginAdjustment,
            leverageMax,
            windowSize,
            amountIn,
            isPrice0
        );
    }

}
